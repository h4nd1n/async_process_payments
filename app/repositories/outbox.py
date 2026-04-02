import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Outbox
from app.schemas.dto import OutboxDTO


class OutboxRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_oldest_unpublished(self) -> OutboxDTO | None:
        stmt = (
            select(Outbox)
            .where(Outbox.published_at.is_(None))
            .order_by(Outbox.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        orm_outbox = await self.session.scalar(stmt)
        return OutboxDTO.model_validate(orm_outbox) if orm_outbox else None

    async def create(self, payment_id: uuid.UUID, payload: dict[str, Any]) -> None:
        orm_outbox = Outbox(
            id=uuid.uuid4(),
            payment_id=payment_id,
            payload=payload,
        )
        self.session.add(orm_outbox)

    async def mark_published(self, outbox_id: uuid.UUID, published_at: datetime) -> None:
        stmt = (
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(published_at=published_at)
        )
        await self.session.execute(stmt)
