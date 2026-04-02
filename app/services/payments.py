import uuid
from typing import Any

from app.exceptions import EntityExistsError
from app.repositories.uow import AbstractUnitOfWork
from app.schemas.payment import PaymentCreateBody
from app.schemas.dto import PaymentDTO


class PaymentService:
    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    async def get_payment(self, payment_id: uuid.UUID) -> PaymentDTO | None:
        async with self.uow:
            return await self.uow.payments.get_by_id(payment_id)

    async def create_payment(
        self,
        body: PaymentCreateBody,
        idempotency_key: str,
    ) -> PaymentDTO:
        async with self.uow:
            existing = await self.uow.payments.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

            try:
                payment_dto = await self.uow.payments.create(
                    amount=body.amount,
                    currency=body.currency.value,
                    description=body.description,
                    metadata=body.metadata,
                    idempotency_key=idempotency_key,
                    webhook_url=str(body.webhook_url),
                )
            except EntityExistsError:
                await self.uow.rollback()
                again = await self.uow.payments.get_by_idempotency_key(idempotency_key)
                if again is not None:
                    return again
                raise

            payload: dict[str, Any] = {
                "event": "payments.new",
                "payment_id": str(payment_dto.id),
            }
            await self.uow.outboxes.create(
                payment_id=payment_dto.id,
                payload=payload
            )

            await self.uow.commit()
            return payment_dto
