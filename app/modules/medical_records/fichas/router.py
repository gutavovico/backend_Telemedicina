from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user, require_roles
from app.modules.auth.models import Usuario
from app.modules.medical_records.models import Paciente
from app.modules.medical_records.fichas import service
from app.modules.medical_records.fichas.schemas import (
    FichaCancelRequest,
    FichaClinicaUpdate,
    FichaCreate,
    FichaListResponse,
    FichaResponse,
)

router = APIRouter(tags=["Fichas Médicas"])


def _rol_nombre(current_user: Usuario) -> str:
    rol = getattr(current_user, "rol", None)
    nombre = getattr(rol, "nombre", None) if rol else None
    return (nombre or "").strip().upper()


def _paciente_propio_id(db: Session, current_user: Usuario, tenant_id: Optional[int]) -> Optional[int]:
    """id_paciente del usuario paciente en su tenant, o None si no tiene perfil."""
    q = db.query(Paciente).filter(Paciente.id_usuario == current_user.id_usuario)
    if tenant_id is not None:
        q = q.filter(Paciente.id_clinica == tenant_id)
    propio = q.first()
    return propio.id_paciente if propio else None


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
    El paciente solo puede emitir para su propio registro (CU09).
    """
    if _rol_nombre(current_user) == "PACIENTE":
        propio_id = _paciente_propio_id(db, current_user, tenant_id)
        if propio_id is None or payload.id_paciente != propio_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes emitir fichas para tu propio registro",
            )
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
    """Retorna las fichas clínicas del tenant según los filtros solicitados.
    El paciente solo ve las suyas (se fuerza el filtro a su registro)."""
    if _rol_nombre(current_user) == "PACIENTE":
        propio_id = _paciente_propio_id(db, current_user, tenant_id)
        if propio_id is None:
            from app.modules.medical_records.fichas.schemas import FichaListResponse

            return FichaListResponse(total=0, items=[])
        id_paciente = propio_id
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
    """Obtiene el detalle completo de una ficha médica con sus secciones dinámicas JSONB.
    El paciente solo puede ver sus propias fichas."""
    ficha = service.obtener_ficha_detalle(
        db=db,
        id_ficha=id_ficha,
        id_clinica=tenant_id,
    )
    if _rol_nombre(current_user) == "PACIENTE":
        propio_id = _paciente_propio_id(db, current_user, tenant_id)
        if propio_id is None or ficha.id_paciente != propio_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes acceso a fichas de otros pacientes",
            )
    return ficha


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
    current_user: Usuario = Depends(
        require_roles(["MEDICO", "ADMIN", "ADMINISTRADOR", "ADMINISTRACION"])
    ),
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
    current_user: Usuario = Depends(
        require_roles(["ADMIN", "ADMINISTRADOR", "ADMINISTRACION", "RECEPCION", "MEDICO"])
    ),
):
    """Cancela una ficha médica con registro de motivo (no permitido para FINALIZADA)."""
    return service.cancelar_ficha(
        db=db,
        id_ficha=id_ficha,
        motivo=payload.motivo_cancelacion,
        id_clinica=tenant_id,
        current_user=current_user,
    )
