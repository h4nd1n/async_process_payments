from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker

from app.api.routes.payments import router as payments_router
from app.config import get_settings
from app.db.session import get_async_session_maker
from app.outbox.relay import outbox_relay_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    broker = RabbitBroker(settings.rabbitmq_url)
    await broker.start()
    stop = asyncio.Event()
    relay_task = asyncio.create_task(
        outbox_relay_loop(broker, get_async_session_maker(), stop),
        name="outbox-relay",
    )
    logger.info("Фоновый outbox relay запущен")
    try:
        yield
    finally:
        stop.set()
        relay_task.cancel()
        try:
            await relay_task
        except asyncio.CancelledError:
            pass
        await broker.stop()
        logger.info("Фоновый outbox relay остановлен")


app = FastAPI(
    title="Асинхронные платежи",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(payments_router, prefix="/api/v1")
