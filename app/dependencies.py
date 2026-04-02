from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import get_settings
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.services.payments import PaymentService


def verify_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    cfg = get_settings()
    if not x_api_key or x_api_key != cfg.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или отсутствующий заголовок X-API-Key",
        )


def get_payment_service(request: Request) -> PaymentService:
    maker = request.app.state.sessionmaker
    uow = SqlAlchemyUnitOfWork(maker)
    return PaymentService(uow=uow)
