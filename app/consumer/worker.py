from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from typing import Any

import certifi
import httpx
from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue
from pydantic import ValidationError

from app.config import get_settings
from app.db.models import Payment, PaymentStatus
from app.db.session import get_async_session_maker
from app.messaging.queues import PAYMENTS_DLQ_QUEUE, PAYMENTS_NEW_QUEUE, RETRY_HEADER
from app.messaging.schemas import PaymentNewMessage

logger = logging.getLogger(__name__)


def _retry_count(msg: RabbitMessage) -> int:
    h = msg.headers or {}
    raw = h.get(RETRY_HEADER, 0)
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return 0
    if raw is None:
        return 0
    return int(raw)


async def send_webhook_with_retries(url: str, payload: dict[str, Any]) -> bool:
    settings = get_settings()
    max_attempts = settings.webhook_max_attempts
    base = settings.webhook_backoff_base_sec
    # В slim-образах неполное системное хранилище доверия для TLS; certifi подключает актуальный пакет Mozilla CA.
    async with httpx.AsyncClient(timeout=30.0, verify=certifi.where()) as client:
        for attempt in range(max_attempts):
            try:
                response = await client.post(url, json=payload)
                if response.is_success:
                    return True
                logger.warning(
                    "Webhook ответил %s для %s (попытка %s)",
                    response.status_code,
                    url,
                    attempt + 1,
                )
            except httpx.RequestError as exc:
                logger.warning("Ошибка HTTP-запроса webhook к %s: %s", url, exc)
            if attempt < max_attempts - 1:
                delay = base * (2**attempt) + random.uniform(0, 0.3)
                await asyncio.sleep(delay)
    logger.error("Доставка webhook не удалась за %s попыток: %s", max_attempts, url)
    return False


async def handle_retry_or_dlq(
    body: dict[str, Any],
    msg: RabbitMessage,
    broker: RabbitBroker,
    exc: Exception,
) -> None:
    settings = get_settings()
    max_retries = settings.consumer_max_process_retries
    current = _retry_count(msg)
    next_count = current + 1
    headers = {RETRY_HEADER: str(next_count)}

    if next_count < max_retries:
        logger.warning(
            "Сбой обработки (попытка %s/%s), повторная публикация: %s",
            next_count,
            max_retries,
            exc,
        )
        await broker.publish(body, queue=PAYMENTS_NEW_QUEUE, persist=True, headers=headers)
    else:
        logger.error(
            "Сбой обработки после %s попыток, отправка в DLQ: %s body=%s",
            max_retries,
            exc,
            body,
        )
        dlq_headers = {**headers, "x-error": str(exc)[:512]}
        await broker.publish(body, queue=PAYMENTS_DLQ_QUEUE, persist=True, headers=dlq_headers)


async def process_payment_message(body: dict[str, Any]) -> None:
    try:
        data = PaymentNewMessage.model_validate(body)
    except ValidationError:
        logger.warning("Некорректное тело сообщения очереди, подтверждаем: %s", body)
        return

    async with get_async_session_maker()() as session:
        payment = await session.get(Payment, data.payment_id)
        if payment is None:
            logger.error("Платёж %s не найден, пропуск", data.payment_id)
            return

        if payment.status != PaymentStatus.pending:
            logger.info("Платёж %s уже в конечном статусе (%s), пропуск", data.payment_id, payment.status)
            return

        webhook_url = payment.webhook_url
        amount = payment.amount
        currency = payment.currency.value
        description = payment.description
        metadata = dict(payment.extra_metadata)
        pid = payment.id

        await asyncio.sleep(random.uniform(2.0, 5.0))

        if random.random() < 0.1:
            new_status = PaymentStatus.failed
        else:
            new_status = PaymentStatus.succeeded

        processed_at = datetime.now(tz=UTC)
        payment.status = new_status
        payment.processed_at = processed_at
        await session.commit()

    payload = {
        "payment_id": str(pid),
        "status": new_status.value,
        "amount": str(amount),
        "currency": currency,
        "description": description,
        "metadata": metadata,
        "processed_at": processed_at.isoformat(),
    }
    await send_webhook_with_retries(webhook_url, payload)


def build_app() -> FastStream:
    settings = get_settings()
    broker = RabbitBroker(settings.rabbitmq_url)

    @broker.subscriber(RabbitQueue(PAYMENTS_NEW_QUEUE, durable=True))
    async def on_payment_new(body: dict, msg: RabbitMessage) -> None:
        try:
            await process_payment_message(body)
        except Exception as exc:
            await handle_retry_or_dlq(body, msg, broker, exc)
        else:
            logger.info("Сообщение о платеже обработано успешно")

    @broker.subscriber(RabbitQueue(PAYMENTS_DLQ_QUEUE, durable=True))
    async def on_dlq(body: dict, msg: RabbitMessage) -> None:
        logger.error("Сообщение в DLQ зафиксировано: %s headers=%s", body, msg.headers)

    return FastStream(broker)


async def _run() -> None:
    logging.basicConfig(level=logging.INFO)
    app = build_app()
    await app.run()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
