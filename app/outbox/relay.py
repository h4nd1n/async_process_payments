import asyncio
import logging
from datetime import UTC, datetime

from collections.abc import Callable

from faststream.rabbit import RabbitBroker

from app.config import get_settings
from app.messaging.queues import PAYMENTS_NEW_QUEUE
from app.repositories.uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


class OutboxRelayService:
    def __init__(self, broker: RabbitBroker, uow_factory: Callable[[], AbstractUnitOfWork]):
        self.broker = broker
        self.uow_factory = uow_factory

    async def process_one_outbox_row(self) -> bool:
        """Опубликовать одну неотправленную запись outbox. True, если строка обработана."""
        async with self.uow_factory() as uow:
            row_dto = await uow.outboxes.get_oldest_unpublished()
            if row_dto is None:
                return False

            await self.broker.publish(
                row_dto.payload,
                queue=PAYMENTS_NEW_QUEUE,
                persist=True,
            )
            await uow.outboxes.mark_published(row_dto.id, datetime.now(tz=UTC))
            return True

    async def run_loop(self, stop_event: asyncio.Event) -> None:
        settings = get_settings()
        interval = settings.outbox_poll_interval_sec
        while not stop_event.is_set():
            try:
                batch_work = False
                while await self.process_one_outbox_row():
                    batch_work = True
                if not batch_work:
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Сбой итерации фонового outbox relay")
                await asyncio.sleep(interval)
