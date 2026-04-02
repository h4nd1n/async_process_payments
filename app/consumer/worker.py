from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from typing import Any
from collections.abc import Callable

import certifi
import httpx
from faststream import Context, ContextRepo, FastStream
from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.session import setup_database
from app.messaging.queues import PAYMENTS_DLQ_QUEUE, PAYMENTS_NEW_QUEUE, RETRY_HEADER
from app.messaging.schemas import PaymentNewMessage
from app.repositories.uow import AbstractUnitOfWork, build_uow_factory

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


class PaymentConsumerService:
    def __init__(self, broker: RabbitBroker, uow_factory: Callable[[], AbstractUnitOfWork]):
        self.broker = broker
        self.uow_factory = uow_factory

    async def send_webhook_with_retries(self, url: str, payload: dict[str, Any]) -> bool:
        settings = get_settings()
        max_attempts = settings.webhook_max_attempts
        base = settings.webhook_backoff_base_sec
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
        self,
        body: dict[str, Any],
        msg: RabbitMessage,
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
            await self.broker.publish(body, queue=PAYMENTS_NEW_QUEUE, persist=True, headers=headers)
        else:
            logger.error(
                "Сбой обработки после %s попыток, отправка в DLQ: %s body=%s",
                max_retries,
                exc,
                body,
            )
            dlq_headers = {**headers, "x-error": str(exc)[:512]}
            await self.broker.publish(body, queue=PAYMENTS_DLQ_QUEUE, persist=True, headers=dlq_headers)

    async def process_payment_message(self, body: dict[str, Any]) -> None:
        try:
            data = PaymentNewMessage.model_validate(body)
        except ValidationError:
            logger.warning("Некорректное тело сообщения очереди, подтверждаем: %s", body)
            return

        async with self.uow_factory() as uow:
            payment_dto = await uow.payments.get_by_id(data.payment_id)
            
            if payment_dto is None:
                logger.error("Платёж %s не найден, пропуск", data.payment_id)
                return

            if payment_dto.status != "pending":
                logger.info("Платёж %s уже в конечном статусе (%s), пропуск", data.payment_id, payment_dto.status)
                return

            webhook_url = payment_dto.webhook_url
            amount = payment_dto.amount
            currency = payment_dto.currency
            description = payment_dto.description
            metadata = dict(payment_dto.extra_metadata)
            pid = payment_dto.id

            await asyncio.sleep(random.uniform(2.0, 5.0))

            if random.random() < 0.1:
                new_status = "failed"
            else:
                new_status = "succeeded"

            processed_at = datetime.now(tz=UTC)
            await uow.payments.update_status(pid, new_status, processed_at)
            await uow.commit()

        payload = {
            "payment_id": str(pid),
            "status": new_status,
            "amount": str(amount),
            "currency": currency,
            "description": description,
            "metadata": metadata,
            "processed_at": processed_at.isoformat(),
        }
        await self.send_webhook_with_retries(webhook_url, payload)


def build_app() -> FastStream:
    settings = get_settings()
    broker = RabbitBroker(settings.rabbitmq_url)
    app = FastStream(broker)

    @app.on_startup
    async def setup_db(context: ContextRepo):
        engine, maker = setup_database(settings.database_url)
        context.set_global("engine", engine)
        context.set_global("sessionmaker", maker)

    @app.after_shutdown
    async def close_db(context: ContextRepo):
        engine = context.get("engine")
        if engine:
            await engine.dispose()

    @broker.subscriber(RabbitQueue(PAYMENTS_NEW_QUEUE, durable=True))
    async def on_payment_new(
        body: dict,
        msg: RabbitMessage,
        sessionmaker: async_sessionmaker[AsyncSession] = Context("sessionmaker")
    ) -> None:
        uow_factory = build_uow_factory(sessionmaker)

        consumer = PaymentConsumerService(broker, uow_factory)
        try:
            await consumer.process_payment_message(body)
        except Exception as exc:
            await consumer.handle_retry_or_dlq(body, msg, exc)
        else:
            logger.info("Сообщение о платеже обработано успешно")

    @broker.subscriber(RabbitQueue(PAYMENTS_DLQ_QUEUE, durable=True))
    async def on_dlq(body: dict, msg: RabbitMessage) -> None:
        logger.error("Сообщение в DLQ зафиксировано: %s headers=%s", body, msg.headers)

    return app


async def _run() -> None:
    logging.basicConfig(level=logging.INFO)
    app = build_app()
    await app.run()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
