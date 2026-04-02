from abc import ABC, abstractmethod
from typing import Any, Protocol

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, Callable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.exceptions import EntityExistsError
from app.repositories.outbox import OutboxRepository
from app.repositories.payment import PaymentRepository
from app.schemas.dto import OutboxDTO, PaymentDTO


class AbstractPaymentRepository(Protocol):
    async def get_by_id(self, obj_id: UUID) -> PaymentDTO | None: ...

    async def create(self, amount: Decimal, currency: str, description: str, metadata: dict[str, Any], idempotency_key: str, webhook_url: str) -> PaymentDTO: ...

    async def get_by_idempotency_key(self, key: str) -> PaymentDTO | None: ...

    async def update_status(self, payment_id: UUID, new_status: str, processed_at: datetime) -> None: ...

class AbstractOutboxRepository(Protocol):
    async def get_oldest_unpublished(self) -> OutboxDTO | None: ...

    async def create(self, payment_id: UUID, payload: dict[str, Any]) -> None: ...
    
    async def mark_published(self, outbox_id: UUID, published_at: datetime) -> None: ...

class AbstractUnitOfWork(ABC):
    payments: AbstractPaymentRepository
    outboxes: AbstractOutboxRepository

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self.session_factory()
        self.payments = PaymentRepository(self.session)
        self.outboxes = OutboxRepository(self.session)
        return await super().__aenter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await super().__aexit__(exc_type, exc_val, exc_tb)
        await self.session.close()

    async def commit(self) -> None:
        try:
            await self.session.commit()
        except IntegrityError as exc:
            raise EntityExistsError(f"Конфликт уникальности: {exc}") from exc

    async def rollback(self) -> None:
        await self.session.rollback()

def build_uow_factory(session_factory: async_sessionmaker[AsyncSession]) -> Callable[[], AbstractUnitOfWork]:
    """Возвращает фабрику создания юнитов работы (UoW), чтобы избежать дублирования."""
    def factory() -> AbstractUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)
    return factory
