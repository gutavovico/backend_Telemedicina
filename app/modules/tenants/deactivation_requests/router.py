from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.multitenancy import require_super_admin
from app.modules.auth.dependencies import require_admin
from app.modules.auth.models import Usuario
from app.modules.tenants.deactivation_requests.schemas import (
    DeactivationDecisionRequest,
    DeactivationListResponse,
    DeactivationRequestCreate,
    DeactivationRequestItem,
    DeactivationResponse,
)
from app.modules.tenants.deactivation_requests.service import (
    create_deactivation_request,
    decide_deactivation_request,
    list_deactivation_requests,
)

router = APIRouter(tags=["CU32 - Tenant Deactivation Requests"])


@router.post(
    "/api/v1/tenant/deactivation-requests",
    response_model=DeactivationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Solicitar baja definitiva de entidad de salud (Admin)",
)
@router.post(
    "/tenant/deactivation-requests",
    response_model=DeactivationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
def submit_deactivation_request(
    payload: DeactivationRequestCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    """Permite al administrador autenticado de un tenant ACTIVO solicitar formalmente la baja."""
    return create_deactivation_request(
        db=db,
        current_user=current_user,
        motivo=payload.motivo,
    )


@router.get(
    "/api/v1/tenant/deactivation-requests",
    response_model=DeactivationListResponse,
    summary="Listar solicitudes de baja de tenants (Super Admin)",
)
@router.get(
    "/tenant/deactivation-requests",
    response_model=DeactivationListResponse,
    include_in_schema=False,
)
def endpoint_list_deactivation_requests(
    status_filter: Optional[str] = Query(None, alias="status", description="PENDING, APPROVED, REJECTED"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_super_admin),
):
    return list_deactivation_requests(db, status_filter, page, per_page)


@router.post(
    "/api/v1/tenant/deactivation-requests/{id_deactivation}/approve",
    response_model=DeactivationRequestItem,
    summary="Aprobar solicitud de baja y aplicar baja lógica (Super Admin)",
)
@router.post(
    "/tenant/deactivation-requests/{id_deactivation}/approve",
    response_model=DeactivationRequestItem,
    include_in_schema=False,
)
def endpoint_approve_deactivation_request(
    id_deactivation: str,
    payload: DeactivationDecisionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_super_admin),
):
    return decide_deactivation_request(db, current_user, id_deactivation, payload, approve=True)


@router.post(
    "/api/v1/tenant/deactivation-requests/{id_deactivation}/reject",
    response_model=DeactivationRequestItem,
    summary="Rechazar solicitud de baja con motivo (Super Admin)",
)
@router.post(
    "/tenant/deactivation-requests/{id_deactivation}/reject",
    response_model=DeactivationRequestItem,
    include_in_schema=False,
)
def endpoint_reject_deactivation_request(
    id_deactivation: str,
    payload: DeactivationDecisionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_super_admin),
):
    return decide_deactivation_request(db, current_user, id_deactivation, payload, approve=False)

