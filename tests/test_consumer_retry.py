from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.consumer import worker
from app.messaging.queues import PAYMENTS_DLQ_QUEUE, PAYMENTS_NEW_QUEUE, RETRY_HEADER


class _FakeRabbitMessage:
    __slots__ = ("headers",)

    def __init__(self, headers: dict[str, Any] | None = None) -> None:
        self.headers = headers or {}


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (None, 0),
        ({RETRY_HEADER: 0}, 0),
        ({RETRY_HEADER: "1"}, 1),
        ({RETRY_HEADER: "broken"}, 0),
    ],
)
def test_retry_count_parsing(headers: dict[str, Any] | None, expected: int) -> None:
    msg = _FakeRabbitMessage(headers)
    assert worker._retry_count(msg) == expected  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_handle_retry_republishes_until_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSUMER_MAX_PROCESS_RETRIES", "3")
    broker = AsyncMock()
    body: dict[str, Any] = {"event": "payments.new", "payment_id": "00000000-0000-0000-0000-000000000001"}

    from app.consumer.worker import PaymentConsumerService
    consumer = PaymentConsumerService(broker, None)

    msg = _FakeRabbitMessage({})
    await consumer.handle_retry_or_dlq(body, msg, RuntimeError("db down"))  # type: ignore[arg-type]
    broker.publish.assert_awaited_once()
    args, kwargs = broker.publish.await_args_list[0]
    assert args[0] == body
    assert kwargs["queue"] == PAYMENTS_NEW_QUEUE
    assert kwargs["headers"][RETRY_HEADER] == "1"

    broker.reset_mock()
    msg2 = _FakeRabbitMessage({RETRY_HEADER: "1"})
    await consumer.handle_retry_or_dlq(body, msg2, RuntimeError("again"))  # type: ignore[arg-type]
    call = broker.publish.await_args
    assert call.kwargs["headers"][RETRY_HEADER] == "2"

    broker.reset_mock()
    msg3 = _FakeRabbitMessage({RETRY_HEADER: "2"})
    await consumer.handle_retry_or_dlq(body, msg3, RuntimeError("last"))  # type: ignore[arg-type]
    call = broker.publish.await_args
    assert call.kwargs["queue"] == PAYMENTS_DLQ_QUEUE
    assert call.kwargs["headers"][RETRY_HEADER] == "3"
    assert "x-error" in call.kwargs["headers"]


@pytest.mark.asyncio
async def test_send_webhook_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBHOOK_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("WEBHOOK_BACKOFF_BASE_SEC", "0.01")
    calls: list[int] = []

    async def fast_sleep(_: float) -> None:
        calls.append(1)

    monkeypatch.setattr(worker.asyncio, "sleep", fast_sleep)

    import httpx
    import respx

    with respx.mock:
        route = respx.post("https://example.test/webhook").mock(
            side_effect=[
                httpx.Response(500),
                httpx.ConnectError("nope"),
                httpx.Response(200),
            ],
        )
        from app.consumer.worker import PaymentConsumerService
        consumer = PaymentConsumerService(AsyncMock(), None)
        ok = await consumer.send_webhook_with_retries(
            "https://example.test/webhook",
            {"payment_id": "x"},
        )
        assert ok is True
        assert route.call_count == 3
        assert calls  # были паузы backoff


@pytest.mark.asyncio
async def test_send_webhook_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBHOOK_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("WEBHOOK_BACKOFF_BASE_SEC", "0.01")

    async def fast_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(worker.asyncio, "sleep", fast_sleep)

    import httpx
    import respx

    with respx.mock:
        route = respx.post("https://example.test/webhook").mock(return_value=httpx.Response(503))
        from app.consumer.worker import PaymentConsumerService
        consumer = PaymentConsumerService(AsyncMock(), None)
        ok = await consumer.send_webhook_with_retries(
            "https://example.test/webhook",
            {"payment_id": "x"},
        )
        assert ok is False
        assert route.call_count == 2
