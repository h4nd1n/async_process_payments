import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, PaymentStatus, Currency
from app.exceptions import EntityExistsError
from app.schemas.dto import PaymentDTO


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, obj_id: uuid.UUID) -> PaymentDTO | None:
        orm_payment = await self.session.get(Payment, obj_id)
        return PaymentDTO.model_validate(orm_payment) if orm_payment else None

    async def create(self, amount: Decimal, currency: str, description: str, metadata: dict[str, Any], idempotency_key: str, webhook_url: str) -> PaymentDTO:
        payment_id = uuid.uuid4()
        orm_payment = Payment(
            id=payment_id,
            amount=amount,
            currency=Currency(currency),
            description=description,
            extra_metadata=metadata,
            status=PaymentStatus.pending,
            idempotency_key=idempotency_key,
            webhook_url=webhook_url,
        )
        self.session.add(orm_payment)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise EntityExistsError(f"Конфликт: {exc}") from exc
        return PaymentDTO.model_validate(orm_payment)

    async def get_by_idempotency_key(self, key: str) -> PaymentDTO | None:
        stmt = select(Payment).where(Payment.idempotency_key == key)
        orm_payment = await self.session.scalar(stmt)
        return PaymentDTO.model_validate(orm_payment) if orm_payment else None

    async def update_status(self, payment_id: uuid.UUID, new_status: str, processed_at: datetime) -> None:
        stmt = (
            update(Payment)
            .where(Payment.id == payment_id)
            .values(status=PaymentStatus(new_status), processed_at=processed_at)
        )
        await self.session.execute(stmt)
