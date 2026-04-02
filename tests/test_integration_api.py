from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.integration

API_KEY = "test-api-key-integration"


def _headers(idxem: str) -> dict[str, str]:
    return {
        "X-API-Key": API_KEY,
        "Idempotency-Key": idxem,
    }


@pytest.mark.asyncio
async def test_create_payment_accepted(api_client) -> None:
    payload = {
        "amount": "10.00",
        "currency": "EUR",
        "description": "integration",
        "metadata": {"ref": "r1"},
        "webhook_url": "https://example.com/webhook",
    }
    r = await api_client.post("/api/v1/payments", json=payload, headers=_headers("idem-create-1"))
    assert r.status_code == 202, r.text
    data = r.json()
    assert "payment_id" in data
    assert data["status"] == "pending"
    assert "created_at" in data


@pytest.mark.asyncio
async def test_idempotency_returns_same_payment(api_client) -> None:
    key = f"idem-{uuid4()}"
    body = {
        "amount": "25.50",
        "currency": "USD",
        "description": "d",
        "metadata": {},
        "webhook_url": "https://example.com/w",
    }
    r1 = await api_client.post("/api/v1/payments", json=body, headers=_headers(key))
    r2 = await api_client.post("/api/v1/payments", json=body, headers=_headers(key))
    assert r1.status_code == 202 and r2.status_code == 202
    assert r1.json()["payment_id"] == r2.json()["payment_id"]


@pytest.mark.asyncio
async def test_get_payment_detail(api_client) -> None:
    body = {
        "amount": "7.00",
        "currency": "RUB",
        "description": "get me",
        "metadata": {"k": "v"},
        "webhook_url": "https://example.com/w",
    }
    created = await api_client.post("/api/v1/payments", json=body, headers=_headers(f"idem-{uuid4()}"))
    pid = created.json()["payment_id"]
    r = await api_client.get(f"/api/v1/payments/{pid}", headers={"X-API-Key": API_KEY})
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == pid
    assert Decimal(d["amount"]) == Decimal("7.00")
    assert d["currency"] == "RUB"
    assert d["metadata"] == {"k": "v"}
    assert d["status"] == "pending"


@pytest.mark.asyncio
async def test_get_unknown_payment_404(api_client) -> None:
    r = await api_client.get(f"/api/v1/payments/{uuid4()}", headers={"X-API-Key": API_KEY})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_missing_api_key_401(api_client) -> None:
    r = await api_client.post(
        "/api/v1/payments",
        json={
            "amount": "1.00",
            "currency": "RUB",
            "description": "x",
            "webhook_url": "https://example.com/w",
        },
        headers={"Idempotency-Key": "z"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_missing_idempotency_422(api_client) -> None:
    r = await api_client.post(
        "/api/v1/payments",
        json={
            "amount": "1.00",
            "currency": "RUB",
            "description": "x",
            "webhook_url": "https://example.com/w",
        },
        headers={"X-API-Key": API_KEY},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_process_payment_message_integration(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    import respx

    from app.consumer.worker import PaymentConsumerService
    from app.db.models import Currency, Payment, PaymentStatus
    from app.config import get_settings
    from app.db.session import setup_database
    from app.repositories.uow import SqlAlchemyUnitOfWork
    from unittest.mock import AsyncMock

    monkeypatch.setenv("WEBHOOK_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("WEBHOOK_BACKOFF_BASE_SEC", "0.01")

    async def no_sleep(*_a, **_kw):
        return None

    monkeypatch.setattr("app.consumer.worker.asyncio.sleep", no_sleep)
    monkeypatch.setattr("app.consumer.worker.random.random", lambda: 0.5)
    monkeypatch.setattr("app.consumer.worker.random.uniform", lambda _a, _b: 0.0)

    hook = "https://processor-test.example/hook"
    payment = Payment(
        amount=Decimal("3.00"),
        currency=Currency.RUB,
        description="consumer int",
        extra_metadata={"a": 1},
        status=PaymentStatus.pending,
        idempotency_key=f"ik-{uuid4()}",
        webhook_url=hook,
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)
    pid = payment.id

    with respx.mock:
        route = respx.post(hook).mock(return_value=httpx.Response(204))
        
        engine, maker = setup_database(get_settings().database_url)
        from app.repositories.uow import build_uow_factory
        uow_factory = build_uow_factory(maker)
        consumer = PaymentConsumerService(broker=AsyncMock(), uow_factory=uow_factory)
        
        await consumer.process_payment_message({"event": "payments.new", "payment_id": str(pid)})

        assert route.call_count >= 1
        
        async with maker() as s:
            refreshed = await s.get(Payment, pid)
            assert refreshed is not None
            assert refreshed.status == PaymentStatus.succeeded
            assert refreshed.processed_at is not None
            
        await engine.dispose()
