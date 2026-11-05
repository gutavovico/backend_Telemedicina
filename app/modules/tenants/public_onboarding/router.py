from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.models import Plan, VersionPlan
from app.modules.tenants.public_onboarding.schemas import (
    TenantRequestCreateResponse,
    TenantRequestTrackingResponse,
)
from app.modules.tenants.public_onboarding.service import (
    create_public_tenant_request,
    get_tracking_status,
)
from app.modules.tenants.subscription_payments.schemas import PlanVersionItem

router = APIRouter(tags=["CU32 - Public Health Entity Onboarding"])


@router.post(
    "/api/v1/public/tenant-requests",
    response_model=TenantRequestCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Registrar solicitud de alta institucional (Público)",
)
@router.post(
    "/public/tenant-requests",
    response_model=TenantRequestCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
def submit_public_tenant_request(
    request: Request,
    nombre: str = Form(..., description="Nombre de la institución de salud"),
    razon_social: Optional[str] = Form(None, description="Razón social legal"),
    nit: str = Form(..., description="Número de Identificación Tributaria"),
    correo: str = Form(..., description="Correo de contacto institucional"),
    telefono: Optional[str] = Form(None, description="Teléfono de contacto"),
    direccion: Optional[str] = Form(None, description="Dirección física"),
    responsable_nombre: str = Form(..., description="Nombre completo del responsable legal"),
    responsable_correo: str = Form(..., description="Correo del responsable"),
    responsable_telefono: Optional[str] = Form(None, description="Teléfono del responsable"),
    plan_version_id: Optional[int] = Form(None, description="ID canónico de la versión del plan"),
    documentos: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    """Endpoint público no autenticado para solicitar alta de nueva clínica/tenant."""
    return create_public_tenant_request(
        db=db,
        nombre=nombre,
        razon_social=razon_social,
        nit=nit,
        correo=correo,
        telefono=telefono,
        direccion=direccion,
        responsable_nombre=responsable_nombre,
        responsable_correo=responsable_correo,
        responsable_telefono=responsable_telefono,
        plan_version_id=plan_version_id,
        documentos=documentos,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.get(
    "/api/v1/public/tenant-requests/{tracking_code}",
    response_model=TenantRequestTrackingResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar estado de solicitud por código de seguimiento",
)
@router.get(
    "/public/tenant-requests/{tracking_code}",
    response_model=TenantRequestTrackingResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_tenant_request_status(
    request: Request,
    tracking_code: str,
    db: Session = Depends(get_db),
):
    """Permite consultar el estado y, solo si corresponde, la credencial temporal."""
    return get_tracking_status(
        db=db,
        tracking_code=tracking_code,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.get(
    "/api/v1/public/plans",
    response_model=List[PlanVersionItem],
    status_code=status.HTTP_200_OK,
    summary="Listar planes activos disponibles para nuevas entidades",
)
@router.get(
    "/public/plans",
    response_model=List[PlanVersionItem],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_public_plans(db: Session = Depends(get_db)):
    """Retorna los planes activos que las instituciones de salud pueden seleccionar al solicitar alta."""
    planes = (
        db.query(VersionPlan)
        .join(Plan, Plan.id == VersionPlan.plan_id)
        .filter(Plan.activo.is_(True), VersionPlan.numero == Plan.version_actual)
        .order_by(VersionPlan.precio_mensual.asc())
        .all()
    )
    return [
        PlanVersionItem(
            id_plan_version=p.id,
            nombre=p.nombre,
            descripcion=p.descripcion,
            precio_mensual=float(p.precio_mensual),
            moneda=p.moneda,
            limite_medicos=p.limite_medicos,
            limite_consultas_mes=p.limite_consultas,
        )
        for p in planes
    ]

