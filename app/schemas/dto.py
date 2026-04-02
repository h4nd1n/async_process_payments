from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PaymentDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: Decimal
    currency: str
    description: str
    extra_metadata: dict[str, Any]
    status: str
    idempotency_key: str
    webhook_url: str
    created_at: datetime | None = None
    processed_at: datetime | None = None


class OutboxDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_id: UUID
    payload: dict[str, Any]
    created_at: datetime | None = None
    published_at: datetime | None = None
