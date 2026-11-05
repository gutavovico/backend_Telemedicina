import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    encrypt_temporary_credential,
    generate_temporary_password,
    hash_password,
)
from app.core.tenant_status import (
    CANONICAL_ACTIVE,
    CANONICAL_INACTIVE,
    CANONICAL_SUSPENDED,
    canonical_tenant_status,
    tenant_status_variants,
)
from app.modules.auth.dependencies import _is_global_super_admin
from app.modules.auth.models import Auditoria, Clinica, Plan, Rol, Usuario, VersionPlan
from app.modules.tenants.models import (
    TenantRequest,
    TenantSubscription,
)
from .schemas import (
    ApproveRequest,
    CommercialAgreementUpdate,
    RejectRequest,
    TenantDetail,
    TenantItem,
    TenantListResponse,
    TenantRequestDetail,
    TenantRequestItem,
    TenantRequestListResponse,
    TenantStateAction,
)


def _auditar_acceso_denegado(db: Session, user: Usuario, accion: str):
    """Deja traza de una acción administrativa rechazada (spec CU30)."""
    try:
        db.add(
            Auditoria(
                id_usuario=user.id_usuario,
                id_clinica=None,
                tabla_afectada="tenant_management",
                registro_id=None,
                accion="ACCESO_DENEGADO",
                descripcion=f"Intento denegado de {accion}",
                datos_anteriores=None,
                datos_nuevos={"accion": accion, "rol": getattr(user, "id_rol", None)},
                direccion_ip=None,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def ensure_super_admin(db: Session, user: Usuario, accion: str = "operación global"):
    if not _is_global_super_admin(user):
        _auditar_acceso_denegado(db, user, accion)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: requiere rol de Super Administrador global",
        )


def _auditar_accion(
    db: Session,
    user: Usuario,
    accion: str,
    tabla: str,
    registro_id: Optional[int],
    datos_ant: Optional[dict],
    datos_nuev: Optional[dict],
    descripcion: str,
):
    aud = Auditoria(
        id_usuario=user.id_usuario,
        id_clinica=None,
        tabla_afectada=tabla,
        registro_id=registro_id,
        accion=accion,
        descripcion=descripcion,
        datos_anteriores=datos_ant,
        datos_nuevos=datos_nuev,
        direccion_ip="127.0.0.1",
    )
    db.add(aud)


def list_tenant_requests(
    db: Session,
    user: Usuario,
    status_filter: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> TenantRequestListResponse:
    ensure_super_admin(db, user, "listar solicitudes de tenant")

    query = db.query(TenantRequest)
    if status_filter:
        query = query.filter(func.upper(TenantRequest.status) == status_filter.upper())

    total = query.count()
    offset = (page - 1) * per_page
    requests = query.order_by(TenantRequest.fecha_creacion.desc()).offset(offset).limit(per_page).all()

    return TenantRequestListResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=[TenantRequestItem.model_validate(r) for r in requests],
    )


def get_tenant_request(
    db: Session,
    user: Usuario,
    id_request: str,
) -> TenantRequestDetail:
    ensure_super_admin(db, user, "consultar detalle de solicitud")

    req = db.query(TenantRequest).filter(TenantRequest.id_request == id_request).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud de tenant no encontrada",
        )

    return TenantRequestDetail.model_validate(req)


def approve_tenant_request(
    db: Session,
    user: Usuario,
    id_request: str,
    payload: ApproveRequest,
) -> TenantRequestDetail:
    ensure_super_admin(db, user, "aprobar solicitud de tenant")

    req = db.query(TenantRequest).filter(TenantRequest.id_request == id_request).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud no encontrada",
        )

    if req.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La solicitud no puede ser aprobada en estado {req.status}",
        )

    if req.row_version != payload.row_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Versión de solicitud obsoleta (conflicto de concurrencia)",
        )

    # Validar NIT duplicado
    if req.nit:
        clinica_existente = db.query(Clinica).filter(Clinica.nit == req.nit).first()
        if clinica_existente:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un tenant activo registrado con el NIT {req.nit}",
            )

    tenant_uuid = str(uuid.uuid4())

    # Validar que la versión canónica seleccionada siga vigente.
    if req.id_version_plan:
        plan = (
            db.query(VersionPlan)
            .join(Plan, Plan.id == VersionPlan.plan_id)
            .filter(
                VersionPlan.id == req.id_version_plan,
                Plan.activo.is_(True),
                VersionPlan.numero == Plan.version_actual,
            )
            .first()
        )
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El plan seleccionado ya no está disponible",
            )

    # Crear Clinica / Tenant
    nueva_clinica = Clinica(
        tenant_id=tenant_uuid,
        nombre=req.institucion_nombre,
        razon_social=req.razon_social,
        nit=req.nit,
        correo=req.correo,
        telefono=req.telefono,
        direccion=req.direccion,
        estado="ACTIVE",
        id_version_plan=req.id_version_plan,
        row_version=1,
    )
    db.add(nueva_clinica)
    db.flush()

    # Crear Rol ADMIN de la clínica
    rol_admin = Rol(
        id_clinica=nueva_clinica.id_clinica,
        nombre="ADMIN",
        descripcion="Administrador del Tenant",
        estado="ACTIVO",
    )
    db.add(rol_admin)
    db.flush()

    # Crear Usuario Administrador de la clínica con credencial aleatoria de un solo uso.
    temporary_password = generate_temporary_password()
    admin_user = Usuario(
        id_clinica=nueva_clinica.id_clinica,
        id_rol=rol_admin.id_rol,
        nombres=req.responsable_nombre,
        apellidos="Administrador",
        correo=req.responsable_correo,
        telefono=req.responsable_telefono,
        password_hash=hash_password(temporary_password),
        estado="ACTIVO",
        token_version=0,
    )
    db.add(admin_user)
    db.flush()

    # Si solicitó un plan, crear la suscripción inicial
    if req.id_version_plan:
        ahora = datetime.now(timezone.utc)
        suscripcion = TenantSubscription(
            id_clinica=nueva_clinica.id_clinica,
            tenant_id=tenant_uuid,
            id_version_plan=req.id_version_plan,
            ciclo="MONTHLY",
            fecha_inicio=ahora,
            fecha_fin=ahora + timedelta(days=30),
            estado="ACTIVE",
            row_version=1,
        )
        db.add(suscripcion)

    # Guardar la credencial cifrada solo para mostrarla durante la ventana segura.
    req.temporary_password_encrypted = encrypt_temporary_credential(temporary_password)
    req.temporary_password_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.TEMP_CREDENTIAL_TTL_MINUTES
    )
    req.temporary_password_reveal_count = 0
    req.temporary_password_used_at = None
    req.temporary_password_changed_at = None
    req.credentials_issued = True

    # Actualizar estado de la solicitud
    antiguos = {"status": req.status, "row_version": req.row_version}
    req.status = "APPROVED"
    req.decision_fecha = datetime.now(timezone.utc)
    req.tenant_id = tenant_uuid
    req.id_clinica = nueva_clinica.id_clinica
    req.row_version += 1

    _auditar_accion(
        db,
        user,
        "APROBAR_TENANT_REQUEST",
        "tenant_requests",
        nueva_clinica.id_clinica,
        antiguos,
        {"status": "APPROVED", "tenant_id": tenant_uuid},
        f"Aprobación de solicitud de onboarding {req.id_request}",
    )

    db.commit()
    db.refresh(req)
    return TenantRequestDetail.model_validate(req)


def reject_tenant_request(
    db: Session,
    user: Usuario,
    id_request: str,
    payload: RejectRequest,
) -> TenantRequestDetail:
    ensure_super_admin(db, user, "rechazar solicitud de tenant")

    req = db.query(TenantRequest).filter(TenantRequest.id_request == id_request).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud no encontrada",
        )

    if req.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La solicitud no puede ser rechazada en estado {req.status}",
        )

    if req.row_version != payload.row_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Versión de solicitud obsoleta (conflicto de concurrencia)",
        )

    antiguos = {"status": req.status, "row_version": req.row_version}
    req.status = "REJECTED"
    req.decision_motivo = payload.reason
    req.decision_fecha = datetime.now(timezone.utc)
    req.row_version += 1

    _auditar_accion(
        db,
        user,
        "RECHAZAR_TENANT_REQUEST",
        "tenant_requests",
        None,
        antiguos,
        {"status": "REJECTED", "motivo": payload.reason},
        f"Rechazo de solicitud de onboarding {req.id_request}: {payload.reason}",
    )

    db.commit()
    db.refresh(req)
    return TenantRequestDetail.model_validate(req)


def _find_clinica(db: Session, tenant_id_or_clinica_id: str) -> Clinica:
    query = db.query(Clinica)
    try:
        clinica_id_int = int(tenant_id_or_clinica_id)
        clinica = query.filter(
            or_(Clinica.id_clinica == clinica_id_int, Clinica.tenant_id == tenant_id_or_clinica_id)
        ).first()
    except ValueError:
        clinica = query.filter(Clinica.tenant_id == tenant_id_or_clinica_id).first()

    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant no encontrado",
        )
    return clinica


def list_tenants(
    db: Session,
    user: Usuario,
    status_filter: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> TenantListResponse:
    ensure_super_admin(db, user, "listar tenants")

    query = db.query(Clinica)
    if status_filter:
        query = query.filter(
            func.upper(Clinica.estado).in_(tenant_status_variants(status_filter))
        )

    total = query.count()
    offset = (page - 1) * per_page
    clinicas = query.order_by(Clinica.id_clinica.asc()).offset(offset).limit(per_page).all()

    return TenantListResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=[TenantItem.model_validate(c) for c in clinicas],
    )


def get_tenant(
    db: Session,
    user: Usuario,
    tenant_id: str,
) -> TenantItem:
    ensure_super_admin(db, user, "consultar tenant")
    clinica = _find_clinica(db, tenant_id)
    return TenantItem.model_validate(clinica)


STATE_TRANSITIONS = {
    "activate": {CANONICAL_INACTIVE: CANONICAL_ACTIVE},
    "reactivate": {CANONICAL_SUSPENDED: CANONICAL_ACTIVE},
    "suspend": {CANONICAL_ACTIVE: CANONICAL_SUSPENDED},
    "deactivate": {
        CANONICAL_ACTIVE: CANONICAL_INACTIVE,
        CANONICAL_SUSPENDED: CANONICAL_INACTIVE,
    },
}


def change_tenant_status(
    db: Session,
    user: Usuario,
    tenant_id: str,
    target_status: str,
    payload: TenantStateAction,
    action: str = "change",
) -> TenantItem:
    ensure_super_admin(db, user, f"cambiar estado de tenant a {target_status}")
    clinica = _find_clinica(db, tenant_id)

    if clinica.row_version != payload.row_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Versión del tenant obsoleta (conflicto de concurrencia)",
        )

    estado_anterior = clinica.estado
    canonical_anterior = canonical_tenant_status(estado_anterior)
    allowed_sources = STATE_TRANSITIONS.get(action)
    if allowed_sources is None or canonical_anterior not in allowed_sources:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Transición no permitida: no se puede ejecutar '{action}' "
                f"desde el estado {canonical_anterior or estado_anterior}"
            ),
        )

    antiguos = {"estado": estado_anterior, "row_version": clinica.row_version}

    clinica.estado = target_status
    clinica.row_version += 1

    _auditar_accion(
        db,
        user,
        f"CAMBIO_ESTADO_{target_status}",
        "clinicas",
        clinica.id_clinica,
        antiguos,
        {"estado": target_status, "motivo": payload.reason, "row_version": clinica.row_version},
        f"Cambio de estado del tenant {clinica.id_clinica} de {estado_anterior} a {target_status}. Motivo: {payload.reason or 'Sin motivo'}",
    )

    db.commit()
    db.refresh(clinica)
    return TenantItem.model_validate(clinica)


def update_commercial_agreement(
    db: Session,
    user: Usuario,
    tenant_id: str,
    payload: CommercialAgreementUpdate,
) -> TenantItem:
    ensure_super_admin(db, user, "actualizar acuerdo comercial")
    clinica = _find_clinica(db, tenant_id)

    if clinica.row_version != payload.row_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Versión del tenant obsoleta (conflicto de concurrencia)",
        )

    antiguos = {
        "plan_id": clinica.plan_id,
        "commercial_notes": clinica.commercial_notes,
        "row_version": clinica.row_version,
    }

    if payload.plan_id is not None:
        plan = (
            db.query(VersionPlan)
            .join(Plan, Plan.id == VersionPlan.plan_id)
            .filter(
                VersionPlan.id == payload.plan_id,
                Plan.activo.is_(True),
                VersionPlan.numero == Plan.version_actual,
            )
            .first()
        )
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El plan seleccionado no existe o no está activo",
            )
        clinica.id_version_plan = payload.plan_id
    if payload.commercial_notes is not None:
        clinica.commercial_notes = payload.commercial_notes
    clinica.row_version += 1

    _auditar_accion(
        db,
        user,
        "ACTUALIZAR_ACUERDO_COMERCIAL",
        "clinicas",
        clinica.id_clinica,
        antiguos,
        {
            "plan_id": clinica.plan_id,
            "commercial_notes": clinica.commercial_notes,
            "row_version": clinica.row_version,
        },
        f"Actualización del acuerdo comercial del tenant {clinica.id_clinica}",
    )

    db.commit()
    db.refresh(clinica)
    return TenantItem.model_validate(clinica)


def get_tenant_request_document(
    db: Session,
    user: Usuario,
    id_request: str,
    doc_index: int,
) -> Tuple[Path, str]:
    """Devuelve el archivo privado de un documento de la solicitud (Super Admin)."""
    ensure_super_admin(db, user, "inspeccionar documento de solicitud")

    req = db.query(TenantRequest).filter(TenantRequest.id_request == id_request).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud de tenant no encontrada",
        )

    try:
        documentos = json.loads(req.documentos_metadata or "[]")
    except (TypeError, ValueError):
        documentos = []
    if not isinstance(documentos, list) or doc_index < 0 or doc_index >= len(documentos):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado en la solicitud",
        )

    documento = documentos[doc_index] or {}
    stored_path = documento.get("stored_path")
    if not stored_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no disponible en el almacenamiento",
        )

    base_dir = Path("uploads/tenant_documents").resolve()
    archivo = Path(stored_path).resolve()
    if base_dir != archivo and base_dir not in archivo.parents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no disponible en el almacenamiento",
        )
    if not archivo.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no disponible en el almacenamiento",
        )

    nombre = documento.get("original_name") or archivo.name
    return archivo, nombre

