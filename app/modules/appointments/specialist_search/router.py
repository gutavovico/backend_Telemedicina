from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, get_required_tenant_id
from app.modules.auth.models import Usuario
from .schemas import BusquedaEspecialistasResponse, EspecialistaDisponibilidadResponse
from .service import buscar_especialistas, obtener_disponibilidad_especialista

router = APIRouter(prefix="", tags=["CU06 - Especialistas"])


@router.get(
    "/especialistas/buscar",
    response_model=BusquedaEspecialistasResponse,
    summary="Buscar especialistas y disponibilidad por filtros",
)
def endpoint_buscar_especialistas(
    nombre: Optional[str] = Query(None, description="Búsqueda por nombre o apellido"),
    especialidad_id: Optional[int] = Query(None, description="ID de especialidad"),
    modalidad: str = Query("AMBAS", pattern="^(PRESENCIAL|TELECONSULTA|AMBAS)$"),
    costo_min: Optional[float] = Query(None, ge=0),
    costo_max: Optional[float] = Query(None, ge=0),
    fecha_inicio: date = Query(..., description="Fecha inicial YYYY-MM-DD"),
    fecha_fin: date = Query(..., description="Fecha final YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_required_tenant_id),
    current_user: Usuario = Depends(get_current_user),
):
    return buscar_especialistas(
        db=db,
        tenant_id=tenant_id,
        nombre=nombre,
        especialidad_id=especialidad_id,
        modalidad=modalidad,
        costo_min=costo_min,
        costo_max=costo_max,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/especialistas/{id_medico}/disponibilidad",
    response_model=EspecialistaDisponibilidadResponse,
    summary="Consultar disponibilidad y perfil de un especialista",
)
def endpoint_disponibilidad_especialista(
    id_medico: int,
    fecha_inicio: date = Query(..., description="Fecha inicial YYYY-MM-DD"),
    fecha_fin: date = Query(..., description="Fecha final YYYY-MM-DD"),
    id_servicio: Optional[int] = Query(None, description="ID del servicio médico opcional"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_required_tenant_id),
    current_user: Usuario = Depends(get_current_user),
):
    return obtener_disponibilidad_especialista(
        db=db,
        tenant_id=tenant_id,
        id_medico=id_medico,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        id_servicio=id_servicio,
    )

