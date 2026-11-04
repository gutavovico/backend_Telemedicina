import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.tenant_status import CANONICAL_ACTIVE, canonical_tenant_status
from app.modules.auth.models import Auditoria, Clinica, Usuario
from app.modules.tenants.models import TenantDeactivationRequest
from app.modules.tenants.deactivation_requests.schemas import (
    DeactivationDecisionRequest,
    DeactivationListResponse,
    DeactivationRequestItem,
    DeactivationResponse,
)


def create_deactivation_request(
    db: Session,
    current_user: Usuario,
    motivo: str,
) -> DeactivationResponse:
    # 1. Validar que el usuario pertenezca a una clínica
    if not current_user.id_clinica:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta autenticada no pertenece a ninguna entidad de salud.",
        )

    # 2. Obtener la clínica
    clinica = db.query(Clinica).filter(Clinica.id_clinica == current_user.id_clinica).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entidad de salud no encontrada.",
        )

    # 3. Solo una entidad activa (ACTIVO legacy o ACTIVE canónico) puede solicitar baja
    if canonical_tenant_status(clinica.estado) != CANONICAL_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Solo una entidad de salud en estado ACTIVO puede solicitar la baja definitiva. Su entidad se encuentra en estado '{clinica.estado}'.",
        )

    # 4. Validar si ya existe una solicitud de baja PENDIENTE
    existing = db.query(TenantDeactivationRequest).filter(
        TenantDeactivationRequest.id_clinica == clinica.id_clinica,
        TenantDeactivationRequest.status == "PENDING",
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una solicitud de baja pendiente para esta entidad.",
        )

    # 5. Crear solicitud de baja en estado PENDING (no se borran datos clínicos)
    req = TenantDeactivationRequest(
        id_deactivation=str(uuid.uuid4()),
        id_clinica=clinica.id_clinica,
        tenant_id=clinica.tenant_id,
        motivo=motivo.strip(),
        solicitante_id=current_user.id_usuario,
        status="PENDING",
        row_version=1,
    )

    db.add(req)
    db.commit()
    db.refresh(req)

    return DeactivationResponse(
        id_deactivation=req.id_deactivation,
        status="PENDING",
        message="Solicitud de baja registrada correctamente. Será evaluada por el Super Administrador.",
    )


def list_deactivation_requests(
    db: Session,
    status_filter: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> DeactivationListResponse:
    query = db.query(TenantDeactivationRequest)
    if status_filter:
        query = query.filter(
            func.upper(TenantDeactivationRequest.status) == status_filter.strip().upper()
        )

    total = query.count()
    offset = (page - 1) * per_page
    solicitudes = (
        query.order_by(TenantDeactivationRequest.fecha_creacion.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    clinicas = {
        c.id_clinica: c
        for c in db.query(Clinica)
        .filter(Clinica.id_clinica.in_([s.id_clinica for s in solicitudes]))
        .all()
    } if solicitudes else {}

    items = [
        DeactivationRequestItem(
            id_deactivation=s.id_deactivation,
            id_clinica=s.id_clinica,
            tenant_id=s.tenant_id,
            institucion=(clinicas.get(s.id_clinica).nombre if clinicas.get(s.id_clinica) else "Entidad"),
            motivo=s.motivo,
            status=s.status,
            row_version=s.row_version,
            decision_motivo=s.decision_motivo,
            decision_fecha=s.decision_fecha,
            fecha_creacion=s.fecha_creacion,
        )
        for s in solicitudes
    ]

    return DeactivationListResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=items,
    )


def decide_deactivation_request(
    db: Session,
    user: Usuario,
    id_deactivation: str,
    payload: DeactivationDecisionRequest,
    approve: bool,
) -> DeactivationRequestItem:
    solicitud = (
        db.query(TenantDeactivationRequest)
        .filter(TenantDeactivationRequest.id_deactivation == id_deactivation)
        .first()
    )
    if not solicitud:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud de baja no encontrada",
        )

    if solicitud.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La solicitud de baja ya fue procesada (estado {solicitud.status})",
        )

    if solicitud.row_version != payload.row_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Versión de la solicitud obsoleta (conflicto de concurrencia)",
        )

    clinica = db.query(Clinica).filter(Clinica.id_clinica == solicitud.id_clinica).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entidad de salud no encontrada",
        )

    motivo = (payload.motivo or "").strip()
    if not approve and len(motivo) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe indicar el motivo del rechazo de la baja",
        )

    estado_anterior = clinica.estado
    solicitud.status = "APPROVED" if approve else "REJECTED"
    solicitud.decision_fecha = datetime.now(timezone.utc)
    solicitud.decision_motivo = motivo or None
    solicitud.decidido_por = user.id_usuario
    solicitud.row_version += 1

    if approve:
        # Baja lógica: se conserva el tenant y todos sus datos clínicos.
        clinica.estado = "INACTIVE"
        clinica.row_version = (clinica.row_version or 1) + 1

    db.add(
        Auditoria(
            id_usuario=user.id_usuario,
            id_clinica=clinica.id_clinica,
            tabla_afectada="tenant_deactivation_requests",
            registro_id=None,
            accion="APROBAR_BAJA_TENANT" if approve else "RECHAZAR_BAJA_TENANT",
            descripcion=(
                f"{'Aprobación' if approve else 'Rechazo'} de la solicitud de baja "
                f"{solicitud.id_deactivation}. Motivo: {motivo or 'Sin motivo'}"
            ),
            datos_anteriores={"estado_tenant": estado_anterior, "status": "PENDING"},
            datos_nuevos={
                "estado_tenant": clinica.estado,
                "status": solicitud.status,
                "motivo": motivo or None,
            },
            direccion_ip=None,
        )
    )

    db.commit()
    db.refresh(solicitud)

    return DeactivationRequestItem(
        id_deactivation=solicitud.id_deactivation,
        id_clinica=solicitud.id_clinica,
        tenant_id=solicitud.tenant_id,
        institucion=clinica.nombre,
        motivo=solicitud.motivo,
        status=solicitud.status,
        row_version=solicitud.row_version,
        decision_motivo=solicitud.decision_motivo,
        decision_fecha=solicitud.decision_fecha,
        fecha_creacion=solicitud.fecha_creacion,
    )
