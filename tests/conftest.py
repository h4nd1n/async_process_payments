from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parent.parent


async def _dispose_app_engine() -> None:
    from app.db.session import dispose_engine

    await dispose_engine()


def _to_asyncpg_dsn(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url.split("postgresql+psycopg2://", 1)[1]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.split("postgresql://", 1)[1]
    return url


@pytest.fixture(scope="session")
def postgres_connection_url() -> str:
    pytest.importorskip("testcontainers")
    from testcontainers.postgres import PostgresContainer

    try:
        with PostgresContainer("postgres:16-alpine") as postgres:
            yield _to_asyncpg_dsn(postgres.get_connection_url())
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Контейнер PostgreSQL (testcontainers) недоступен: {exc}")


@pytest.fixture(scope="session")
def rabbitmq_connection_url() -> str:
    pytest.importorskip("testcontainers")
    pytest.importorskip("pika")
    from testcontainers.rabbitmq import RabbitMqContainer

    try:
        with RabbitMqContainer("rabbitmq:3.13-alpine") as rabbit:
            host = rabbit.get_container_host_ip()
            port = rabbit.get_exposed_port(rabbit.port)
            user = quote(rabbit.username, safe="")
            password = quote(rabbit.password, safe="")
            yield f"amqp://{user}:{password}@{host}:{port}/"
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Контейнер RabbitMQ (testcontainers) недоступен: {exc}")


@pytest.fixture(scope="session")
def _integration_db(postgres_connection_url: str, rabbitmq_connection_url: str) -> None:
    os.environ["DATABASE_URL"] = postgres_connection_url
    os.environ["RABBITMQ_URL"] = rabbitmq_connection_url
    os.environ.setdefault("API_KEY", "test-api-key-integration")

    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            result.stderr or result.stdout or f"alembic завершился с кодом {result.returncode}",
        )

    yield

    asyncio.run(_dispose_app_engine())


@pytest.fixture
async def api_client(_integration_db: None) -> AsyncIterator:
    """У каждого теста новый async engine: пул привязан к циклу событий предыдущего (уже закрытого) теста."""
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    await _dispose_app_engine()
    try:
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        await _dispose_app_engine()


@pytest.fixture
async def db_session(_integration_db: None):
    from app.db.session import get_async_session_maker

    await _dispose_app_engine()
    try:
        maker = get_async_session_maker()
        async with maker() as session:
            yield session
            await session.rollback()
    finally:
        await _dispose_app_engine()
