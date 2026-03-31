from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.models import Currency
from app.schemas.payment import PaymentCreateBody


def test_payment_create_valid_minimal():
    body = PaymentCreateBody(
        amount=Decimal("100.50"),
        currency=Currency.RUB,
        description="Заказ",
        webhook_url="https://example.com/hook",
    )
    assert body.metadata == {}
    assert body.amount == Decimal("100.50")


def test_payment_create_rejects_non_positive_amount():
    with pytest.raises(ValidationError):
        PaymentCreateBody(
            amount=Decimal("0"),
            currency=Currency.USD,
            description="x",
            webhook_url="https://example.com/h",
        )


def test_payment_create_rejects_invalid_currency_string():
    with pytest.raises(ValidationError):
        PaymentCreateBody(
            amount=Decimal("1.00"),
            currency="GBP",  # type: ignore[arg-type]
            description="x",
            webhook_url="https://example.com/h",
        )
