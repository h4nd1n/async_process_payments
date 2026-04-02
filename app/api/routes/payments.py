from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.dependencies import get_payment_service, verify_api_key
from app.schemas.payment import PaymentCreateBody, PaymentCreateResponse, PaymentDetailResponse
from app.services.payments import PaymentService

router = APIRouter(prefix="/payments", tags=["Платежи"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def create_payment(
    body: PaymentCreateBody,
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> PaymentCreateResponse:
    payment = await payment_service.create_payment(body, idempotency_key)
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
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentDetailResponse:
    payment = await payment_service.get_payment(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Платёж не найден")
    return PaymentDetailResponse.from_payment(payment)
