from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker

from app.api.routes.payments import router as payments_router
from app.config import get_settings
from app.db.session import setup_database
from app.outbox.relay import OutboxRelayService
from app.repositories.uow import build_uow_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine, maker = setup_database(settings.database_url)
    app.state.sessionmaker = maker
    app.state.engine = engine

    broker = RabbitBroker(settings.rabbitmq_url)
    await broker.start()
    
    uow_factory = build_uow_factory(maker)
        
    relay_service = OutboxRelayService(broker, uow_factory)
    
    stop = asyncio.Event()
    relay_task = asyncio.create_task(
        relay_service.run_loop(stop),
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
        await engine.dispose()
        logger.info("Фоновый outbox relay остановлен")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Асинхронные платежи",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(payments_router, prefix="/api/v1")
    return app

app = create_app()
