from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Outbox, Payment, PaymentStatus
from app.schemas.payment import PaymentCreateBody


async def get_payment_by_id(session: AsyncSession, payment_id: uuid.UUID) -> Payment | None:
    return await session.get(Payment, payment_id)


async def get_payment_by_idempotency_key(session: AsyncSession, key: str) -> Payment | None:
    stmt = select(Payment).where(Payment.idempotency_key == key)
    return await session.scalar(stmt)


async def create_payment_with_outbox(
    session: AsyncSession,
    body: PaymentCreateBody,
    idempotency_key: str,
) -> Payment:
    existing = await get_payment_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing

    payment = Payment(
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        extra_metadata=body.metadata,
        status=PaymentStatus.pending,
        idempotency_key=idempotency_key,
        webhook_url=str(body.webhook_url),
    )
    session.add(payment)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        again = await get_payment_by_idempotency_key(session, idempotency_key)
        if again is not None:
            return again
        raise

    payload: dict[str, Any] = {
        "event": "payments.new",
        "payment_id": str(payment.id),
    }
    outbox = Outbox(payment_id=payment.id, payload=payload)
    session.add(outbox)

    await session.flush()
    return payment
