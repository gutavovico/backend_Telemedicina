from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, get_required_tenant_id, require_admin
from app.modules.auth.models import Usuario
from .schemas import (
    CheckoutResponse,
    CheckoutStatusResponse,
    CreateCheckoutRequest,
    CurrentSubscriptionResponse,
    PlanVersionItem,
    ReceiptMetadataResponse,
    SubscriptionPaymentHistoryResponse,
)
from .service import (
    build_subscription_receipt_pdf,
    create_subscription_checkout,
    get_current_subscription,
    get_receipt_metadata,
    list_active_plans,
    list_subscription_payments,
    procesar_webhook_suscripcion,
    sincronizar_checkout_suscripcion,
)

router = APIRouter(prefix="", tags=["CU31 - Suscripciones de Tenant"])


@router.get(
    "/subscriptions/current",
    response_model=CurrentSubscriptionResponse,
    summary="Consultar suscripción actual y límites del tenant",
)
def endpoint_get_current_subscription(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_required_tenant_id),
    current_user: Usuario = Depends(require_admin),
):
    return get_current_subscription(db, tenant_id)


@router.get(
    "/subscriptions/plans",
    response_model=List[PlanVersionItem],
    summary="Listar planes activos disponibles para contratación",
)
def endpoint_list_plans(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return list_active_plans(db)


@router.post(
    "/subscriptions/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear sesión de checkout en Stripe para suscripción del tenant",
)
def endpoint_create_subscription_checkout(
    payload: CreateCheckoutRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_required_tenant_id),
    current_user: Usuario = Depends(require_admin),
):
    return create_subscription_checkout(
        db=db,
        tenant_id=tenant_id,
        user=current_user,
        plan_version_id=payload.plan_version_id,
        cycle=payload.cycle,
    )


@router.get(
    "/subscription-payments",
    response_model=SubscriptionPaymentHistoryResponse,
    summary="Historial de pagos de suscripción del tenant",
)
def endpoint_list_subscription_payments(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_required_tenant_id),
    current_user: Usuario = Depends(require_admin),
):
    return list_subscription_payments(db, tenant_id, page, per_page)


@router.get(
    "/subscription-payments/{id_pago}/receipt",
    response_model=ReceiptMetadataResponse,
    summary="Metadatos del comprobante de suscripción",
)
def endpoint_get_receipt_metadata(
    id_pago: str,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_required_tenant_id),
    current_user: Usuario = Depends(require_admin),
):
    return get_receipt_metadata(db, tenant_id, id_pago)


@router.get(
    "/subscription-payments/{id_pago}/receipt/pdf",
    summary="Descargar comprobante de pago de suscripción en PDF",
    response_class=Response,
)
def endpoint_download_receipt_pdf(
    id_pago: str,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_required_tenant_id),
    current_user: Usuario = Depends(require_admin),
):
    pdf_bytes = build_subscription_receipt_pdf(db, tenant_id, id_pago)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="comprobante_{id_pago}.pdf"'},
    )


@router.post(
    "/subscriptions/checkout/{id_pago}/synchronize",
    response_model=CheckoutStatusResponse,
    summary="Sincronizar el estado real de un checkout de suscripción",
)
def endpoint_synchronize_subscription_checkout(
    id_pago: str,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_required_tenant_id),
    current_user: Usuario = Depends(require_admin),
):
    pago = sincronizar_checkout_suscripcion(db, tenant_id, id_pago)
    return CheckoutStatusResponse(
        id_pago=pago.id_pago_suscripcion,
        estado=pago.estado,
        confirmado=pago.estado == "PAGADO",
        checkout_url=pago.url_checkout,
        expira_en=pago.expira_en,
    )


@router.post(
    "/payments/webhook/stripe/subscription",
    summary="Webhook firmado de confirmación de pago de suscripción",
)
async def endpoint_subscription_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    return procesar_webhook_suscripcion(db, payload, signature)

