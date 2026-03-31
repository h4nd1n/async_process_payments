from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.dependencies import verify_api_key
from app.schemas.payment import PaymentCreateBody, PaymentCreateResponse, PaymentDetailResponse
from app.services import payments as payments_service

router = APIRouter(prefix="/payments", tags=["Платежи"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def create_payment(
    body: PaymentCreateBody,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> PaymentCreateResponse:
    payment = await payments_service.create_payment_with_outbox(session, body, idempotency_key)
    return PaymentCreateResponse(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    dependencies=[Depends(verify_api_key)],
)
async def get_payment(
    payment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentDetailResponse:
    payment = await payments_service.get_payment_by_id(session, payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Платёж не найден")
    return PaymentDetailResponse.from_payment(payment)
