from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies.tenant import require_super_admin
from app.modules.auth.models import Usuario
from app.modules.clinicas.schemas import (
    ClinicaEstadoResponse,
    ClinicaEstadoUpdate,
    ClinicaListResponse,
)
from app.modules.clinicas.service import list_clinicas, update_clinica_estado

router = APIRouter(prefix="/clinicas", tags=["Clínicas (Super Admin)"])


@router.get("", response_model=ClinicaListResponse)
def get_clinicas(
    estado: Optional[str] = Query(None, description="Filtrar por estado (ACTIVO, INACTIVO, SUSPENDIDO)"),
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(20, ge=1, le=100, description="Items por página"),
    current_user: Usuario = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    List all clinics in the platform (Super Admin only).
    """
    total, items = list_clinicas(db, estado=estado, page=page, per_page=per_page)
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
    current_user: Usuario = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    Update the operational status of a clinic (Super Admin only).
    """
    clinica = update_clinica_estado(db, clinica_id=clinica_id, nuevo_estado=payload.estado)
    return ClinicaEstadoResponse(
        clinica_id=clinica.id_clinica,
        nombre=clinica.nombre,
        estado=clinica.estado,
        mensaje="Estado actualizado correctamente",
    )
