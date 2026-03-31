from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PaymentNewMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: str = Field(default="payments.new")
    payment_id: UUID
