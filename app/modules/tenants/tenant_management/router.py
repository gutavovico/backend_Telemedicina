from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.multitenancy import is_super_admin
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Usuario
from .schemas import (
    ApproveRequest,
    CommercialAgreementUpdate,
    RejectRequest,
    TenantContextResponse,
    TenantDetail,
    TenantItem,
    TenantListResponse,
    TenantRequestDetail,
    TenantRequestListResponse,
    TenantStateAction,
)
from .service import (
    approve_tenant_request,
    change_tenant_status,
    get_tenant,
    get_tenant_request,
    get_tenant_request_document,
    list_tenant_requests,
    list_tenants,
    reject_tenant_request,
    update_commercial_agreement,
)

router = APIRouter(prefix="", tags=["CU30 - Gestión de Tenants"])


@router.get(
    "/tenant-requests",
    response_model=TenantRequestListResponse,
    summary="Listar solicitudes de onboarding de tenant (Super Admin)",
)
def endpoint_list_tenant_requests(
    status: Optional[str] = Query(None, description="PENDING, APPROVED, REJECTED"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return list_tenant_requests(db, current_user, status, page, per_page)


@router.get(
    "/tenant-requests/{id_request}/documents/{doc_index}",
    summary="Descargar documento legal de una solicitud (Super Admin)",
)
def endpoint_download_tenant_request_document(
    id_request: str,
    doc_index: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    archivo, nombre = get_tenant_request_document(db, current_user, id_request, doc_index)
    return FileResponse(path=str(archivo), filename=nombre)


@router.get(
    "/tenant-requests/{id_request}",
    response_model=TenantRequestDetail,
    summary="Detalle de solicitud de tenant con documentos (Super Admin)",
)
def endpoint_get_tenant_request(
    id_request: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return get_tenant_request(db, current_user, id_request)


@router.post(
    "/tenant-requests/{id_request}/approve",
    response_model=TenantRequestDetail,
    summary="Aprobar solicitud y dar de alta tenant y usuario administrador",
)
def endpoint_approve_tenant_request(
    id_request: str,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return approve_tenant_request(db, current_user, id_request, payload)


@router.post(
    "/tenant-requests/{id_request}/reject",
    response_model=TenantRequestDetail,
    summary="Rechazar solicitud de tenant con motivo",
)
def endpoint_reject_tenant_request(
    id_request: str,
    payload: RejectRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return reject_tenant_request(db, current_user, id_request, payload)


@router.get(
    "/tenants",
    response_model=TenantListResponse,
    summary="Listar tenants de la plataforma (Super Admin)",
)
def endpoint_list_tenants(
    status: Optional[str] = Query(None, description="ACTIVE, SUSPENDED, INACTIVE"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return list_tenants(db, current_user, status, page, per_page)


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantItem,
    summary="Detalle de un tenant (Super Admin)",
)
def endpoint_get_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return get_tenant(db, current_user, tenant_id)


@router.post(
    "/tenants/{tenant_id}/activate",
    response_model=TenantItem,
    summary="Activar tenant",
)
def endpoint_activate_tenant(
    tenant_id: str,
    payload: TenantStateAction,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return change_tenant_status(db, current_user, tenant_id, "ACTIVE", payload, action="activate")


@router.post(
    "/tenants/{tenant_id}/suspend",
    response_model=TenantItem,
    summary="Suspender tenant por mora u otra causa",
)
def endpoint_suspend_tenant(
    tenant_id: str,
    payload: TenantStateAction,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return change_tenant_status(db, current_user, tenant_id, "SUSPENDED", payload, action="suspend")


@router.post(
    "/tenants/{tenant_id}/reactivate",
    response_model=TenantItem,
    summary="Reactivar tenant suspendido",
)
def endpoint_reactivate_tenant(
    tenant_id: str,
    payload: TenantStateAction,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return change_tenant_status(db, current_user, tenant_id, "ACTIVE", payload, action="reactivate")


@router.post(
    "/tenants/{tenant_id}/deactivate",
    response_model=TenantItem,
    summary="Dar de baja lógica a un tenant (no borra datos clínicos)",
)
def endpoint_deactivate_tenant(
    tenant_id: str,
    payload: TenantStateAction,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return change_tenant_status(db, current_user, tenant_id, "INACTIVE", payload, action="deactivate")


@router.put(
    "/tenants/{tenant_id}/commercial-agreement",
    response_model=TenantItem,
    summary="Actualizar plan referenciado y notas comerciales de un tenant",
)
def endpoint_update_commercial_agreement(
    tenant_id: str,
    payload: CommercialAgreementUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return update_commercial_agreement(db, current_user, tenant_id, payload)


def _resolve_contexto_medico_opcional(db, current_user, x_tenant_id):
    """Contexto CU29 sin bloquear a médicos con vínculo INVITADO/SUSPENDIDO.

    `/tenant/context` es el shell de la app: debe responder aunque el médico
    todavía no haya aceptado su invitación, para que pueda llegar a la bandeja
    de vinculaciones donde se acepta. Sin `X-Tenant-ID`, un `403` por falta
    de vínculo activo se traduce a `None` (sin contexto clínico); con header
    explícito se conserva el rechazo estricto (CU29).
    """
    from app.modules.appointments.doctor_entity_links.dependencies import (
        resolve_active_medical_link,
    )

    try:
        return resolve_active_medical_link(db, current_user, x_tenant_id)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN and not x_tenant_id:
            return None
        raise


@router.get(
    "/tenant/context",
    response_model=TenantContextResponse,
    tags=["Tenant Context"],
    summary="Retorna el contexto del tenant autenticado y la identidad del usuario",
)
def get_tenant_context(
    response: Response,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna el tenant (clínica) y el contexto de identidad del usuario."""
    super_admin = is_super_admin(current_user)

    clinica_id: Optional[int] = None
    clinica_nombre: str = ""
    clinica_estado: Optional[str] = None

    if super_admin:
        if x_tenant_id:
            try:
                target_id = int(x_tenant_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Encabezado X-Tenant-ID inválido",
                )
            clinica = db.query(Clinica).filter(Clinica.id_clinica == target_id).first()
            if not clinica:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Clínica no encontrada",
                )
            if (clinica.estado or "").upper() not in ("ACTIVO", "ACTIVE"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Clínica inactiva. Contacte al administrador.",
                )
            clinica_id = clinica.id_clinica
            clinica_nombre = clinica.nombre
            clinica_estado = clinica.estado
    else:
        contexto_medico = _resolve_contexto_medico_opcional(db, current_user, x_tenant_id)
        tenant_objetivo = (
            contexto_medico.link.id_clinica
            if contexto_medico is not None
            else current_user.id_clinica
        )
        if tenant_objetivo is not None:
            clinica = (
                db.query(Clinica)
                .filter(Clinica.id_clinica == tenant_objetivo)
                .first()
            )
            if not clinica:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Clínica no encontrada",
                )
            if (clinica.estado or "").upper() not in ("ACTIVO", "ACTIVE"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Clínica inactiva. Contacte al administrador.",
                )
            clinica_id = clinica.id_clinica
            clinica_nombre = clinica.nombre
            clinica_estado = clinica.estado

    permisos: List[str] = []
    roles_efectivos: List[str] = []
    rol_nombre = ""
    if not super_admin:
        contexto_medico = _resolve_contexto_medico_opcional(db, current_user, x_tenant_id)
        if contexto_medico is not None:
            rol_nombre = contexto_medico.rol_principal or ""
            roles_efectivos = list(contexto_medico.roles)
            permisos = list(contexto_medico.permisos)

    if not permisos and not roles_efectivos:
        user_with_perms = (
            db.query(Usuario)
            .options(joinedload(Usuario.rol_rel))
            .filter(Usuario.id_usuario == current_user.id_usuario)
            .first()
        )
        if user_with_perms and user_with_perms.rol_rel:
            rol_nombre = user_with_perms.rol_rel.nombre
            roles_efectivos = [rol_nombre]
            for p in getattr(user_with_perms.rol_rel, "permisos", []):
                if getattr(p, "estado", "") and p.estado.upper() != "ACTIVO":
                    continue
                if getattr(p, "nombre", None) and p.nombre not in permisos:
                    permisos.append(p.nombre)
                if getattr(p, "modulo", None) and getattr(p, "accion", None):
                    code = f"{p.modulo}.{p.accion}"
                    if code not in permisos:
                        permisos.append(code)
    elif rol_nombre and rol_nombre not in roles_efectivos:
        roles_efectivos.insert(0, rol_nombre)

    from app.modules.tenants.entity_configuration.dependencies import puede_configurar
    from app.modules.tenants.entity_configuration.service import COLORES_PREDETERMINADOS, identidad, tema_personal

    response.headers["Cache-Control"] = "private, no-store"
    tema = None
    if not super_admin and clinica_id is not None and puede_configurar(current_user, clinica):
        tema = tema_personal(db, current_user) or COLORES_PREDETERMINADOS
    return TenantContextResponse(
        marca=identidad(clinica) if clinica_id is not None else None,
        tema=tema,
        clinica_id=clinica_id,
        clinica_nombre=clinica_nombre,
        clinica_estado=clinica_estado,
        usuario_id=current_user.id_usuario,
        usuario_nombres=current_user.nombres,
        usuario_apellidos=current_user.apellidos,
        usuario_correo=current_user.correo,
        rol=rol_nombre,
        roles=roles_efectivos,
        permisos=permisos,
        es_super_admin=super_admin,
    )


