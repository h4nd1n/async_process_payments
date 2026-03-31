from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from faststream.rabbit import RabbitBroker

from app.config import get_settings
from app.db.models import Outbox
from app.messaging.queues import PAYMENTS_NEW_QUEUE

logger = logging.getLogger(__name__)


async def process_one_outbox_row(
    session: AsyncSession,
    broker: RabbitBroker,
) -> bool:
    """Опубликовать одну неотправленную запись outbox. True, если строка обработана."""
    stmt = (
        select(Outbox)
        .where(Outbox.published_at.is_(None))
        .order_by(Outbox.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    row = await session.scalar(stmt)
    if row is None:
        return False

    await broker.publish(
        row.payload,
        queue=PAYMENTS_NEW_QUEUE,
        persist=True,
    )
    row.published_at = datetime.now(tz=UTC)
    return True


async def outbox_relay_loop(
    broker: RabbitBroker,
    session_factory: async_sessionmaker[AsyncSession],
    stop: asyncio.Event,
) -> None:
    settings = get_settings()
    interval = settings.outbox_poll_interval_sec
    while not stop.is_set():
        try:
            batch_work = False
            async with session_factory() as session:
                async with session.begin():
                    while await process_one_outbox_row(session, broker):
                        batch_work = True
            if not batch_work:
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Сбой итерации фонового outbox relay")
            await asyncio.sleep(interval)
