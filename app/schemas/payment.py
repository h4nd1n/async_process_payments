from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.db.models import Currency, Payment, PaymentStatus


class PaymentCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: Currency
    description: str = Field(min_length=1, max_length=4096)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl

    @field_validator("amount")
    @classmethod
    def amount_two_decimals(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))


class PaymentCreateResponse(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None

    @classmethod
    def from_payment(cls, p: Payment) -> PaymentDetailResponse:
        return cls(
            id=p.id,
            amount=p.amount,
            currency=p.currency,
            description=p.description,
            metadata=p.extra_metadata,
            status=p.status,
            idempotency_key=p.idempotency_key,
            webhook_url=p.webhook_url,
            created_at=p.created_at,
            processed_at=p.processed_at,
        )
