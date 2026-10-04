from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.multitenancy import require_super_admin
from app.modules.auth.models import Usuario
from app.modules.auth.audit.service import registrar_evento
from app.modules.auth.clinicas import service
from app.modules.auth.clinicas.schemas import (
    AdminSummary,
    ClinicaEstadoResponse,
    ClinicaEstadoUpdate,
    ClinicaListResponse,
    ClinicaRegistroRequest,
    ClinicaRegistroResponse,
    ClinicaSummary,
)

router = APIRouter(prefix="/clinicas", tags=["Clínicas (Super Admin)"])


@router.get("", response_model=ClinicaListResponse)
def get_clinicas(
    estado: Optional[str] = Query(None, description="Filtrar por estado (ACTIVO, INACTIVO, SUSPENDIDO)"),
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(20, ge=1, le=100, description="Items por página"),
    current_user: Usuario = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Lista las clínicas de la plataforma (solo Super Admin)."""
    total, items = service.list_clinicas(db, estado=estado, page=page, per_page=per_page)
    return ClinicaListResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=items,
    )


@router.patch("/{clinica_id}/estado", response_model=ClinicaEstadoResponse)
def patch_clinica_estado(
    clinica_id: int,
    payload: ClinicaEstadoUpdate,
    request: Request,
    current_user: Usuario = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Actualiza el estado operativo de una clínica (solo Super Admin)."""
    clinica = service.update_clinica_estado(db, clinica_id=clinica_id, nuevo_estado=payload.estado)
    ip = request.client.host if request.client else None
    registrar_evento(
        db,
        id_usuario=current_user.id_usuario,
        accion="UPDATE",
        id_clinica=clinica.id_clinica,
        tabla_afectada="clinicas",
        registro_id=clinica.id_clinica,
        descripcion=f"Cambio de estado de clínica a {clinica.estado}",
        direccion_ip=ip,
    )
    return ClinicaEstadoResponse(
        clinica_id=clinica.id_clinica,
        nombre=clinica.nombre,
        estado=clinica.estado,
        mensaje="Estado actualizado correctamente",
    )


@router.post(
    "/registrar",
    response_model=ClinicaRegistroResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_registrar_clinica(
    payload: ClinicaRegistroRequest,
    db: Session = Depends(get_db),
):
    """Onboarding público: registra una clínica y su cuenta administradora."""
    clinica, admin_user = service.registrar_clinica(db, data=payload)
    return ClinicaRegistroResponse(
        clinica=ClinicaSummary(
            id_clinica=clinica.id_clinica,
            nombre=clinica.nombre,
            estado=clinica.estado,
        ),
        administrador=AdminSummary(
            id_usuario=admin_user.id_usuario,
            correo=admin_user.correo,
        ),
    )
