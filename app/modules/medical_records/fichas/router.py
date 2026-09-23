from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.fichas import service
from app.modules.medical_records.fichas.schemas import (
    FichaCancelRequest,
    FichaClinicaUpdate,
    FichaCreate,
    FichaListResponse,
    FichaResponse,
)

router = APIRouter(tags=["Fichas Médicas"])


def _resolve_tenant_id(
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
    current_user: Usuario = Depends(get_current_user),
) -> int:
    """Garantiza la obtención del tenant_id autenticado."""
    if tenant_id is not None:
        return tenant_id
    if current_user and current_user.id_clinica is not None:
        return current_user.id_clinica
    return 1


@router.post(
    "",
    response_model=FichaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Emisión atómica de ficha médica",
)
def emitir_ficha(
    payload: FichaCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_resolve_tenant_id),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Emite una ficha médica generando correlativo único (FICH-YYYYMMDD-XXXX)
    y validando disponibilidad de turno en tiempo real (409 Conflict ante colisión).
    """
    return service.crear_ficha(
        db=db,
        payload=payload,
        id_clinica=tenant_id,
        current_user=current_user,
    )


@router.get(
    "",
    response_model=FichaListResponse,
    summary="Listado filtrable y paginado de fichas médicas",
)
def listar_fichas(
    id_paciente: Optional[int] = Query(None, description="Filtrar por paciente"),
    id_medico: Optional[int] = Query(None, description="Filtrar por médico"),
    id_especialidad: Optional[int] = Query(None, description="Filtrar por especialidad"),
    fecha: Optional[date] = Query(None, description="Filtrar por fecha de atención (YYYY-MM-DD)"),
    estado: Optional[str] = Query(None, description="Filtrar por estado (EMITIDA, EN_ATENCION, FINALIZADA, CANCELADA)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_resolve_tenant_id),
    current_user: Usuario = Depends(get_current_user),
):
    """Retorna las fichas clínicas del tenant según los filtros solicitados."""
    return service.listar_fichas(
        db=db,
        id_clinica=tenant_id,
        id_paciente=id_paciente,
        id_medico=id_medico,
        id_especialidad=id_especialidad,
        fecha=fecha,
        estado=estado,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{id_ficha}",
    response_model=FichaResponse,
    summary="Obtener detalle de ficha médica",
)
def detalle_ficha(
    id_ficha: str,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_resolve_tenant_id),
    current_user: Usuario = Depends(get_current_user),
):
    """Obtiene el detalle completo de una ficha médica con sus secciones dinámicas JSONB."""
    return service.obtener_ficha_detalle(
        db=db,
        id_ficha=id_ficha,
        id_clinica=tenant_id,
    )


@router.patch(
    "/{id_ficha}/clinica",
    response_model=FichaResponse,
    summary="Llenado clínico médico de ficha (CIE-10, notas, signos vitales)",
)
def actualizar_clinica(
    id_ficha: str,
    payload: FichaClinicaUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_resolve_tenant_id),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Permite al médico registrar signos vitales, secciones dinámicas JSONB,
    diagnóstico CIE-10 y notas de evolución.
    """
    return service.actualizar_clinica_ficha(
        db=db,
        id_ficha=id_ficha,
        payload=payload,
        id_clinica=tenant_id,
        current_user=current_user,
    )


@router.post(
    "/{id_ficha}/cancelar",
    response_model=FichaResponse,
    summary="Cancelar ficha médica",
)
def cancelar_ficha(
    id_ficha: str,
    payload: FichaCancelRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_resolve_tenant_id),
    current_user: Usuario = Depends(get_current_user),
):
    """Cancela una ficha médica con registro de motivo (no permitido para FINALIZADA)."""
    return service.cancelar_ficha(
        db=db,
        id_ficha=id_ficha,
        motivo=payload.motivo_cancelacion,
        id_clinica=tenant_id,
        current_user=current_user,
    )
