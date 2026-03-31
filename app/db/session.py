from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    global _engine, _async_session_maker
    if _async_session_maker is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
        )
        _async_session_maker = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_maker


async def dispose_engine() -> None:
    """Закрыть пул соединений движка (например между тестами или при смене DATABASE_URL)."""
    global _engine, _async_session_maker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _async_session_maker = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    maker = get_async_session_maker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
