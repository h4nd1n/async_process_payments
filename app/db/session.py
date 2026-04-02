from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def setup_database(database_url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Создаёт пул соединений и фабрику сессий на основе переданного URL."""
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )
    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, maker
