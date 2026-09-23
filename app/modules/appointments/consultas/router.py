from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.appointments.consultas import service
from app.modules.appointments.consultas.schemas import (
    CitaCreate,
    CitaListResponse,
    CitaResponse,
    CitaUpdate,
    HorarioSlot,
)

router = APIRouter(tags=["Citas y Consultas (Appointments)"])


@router.post(
    "",
    response_model=CitaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agendar una nueva cita médica",
    description="Registra una nueva cita médica vinculando a un paciente y a un especialista."
)
def agendar_cita(
    datos: CitaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        return service.crear_cita(db, datos)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error al agendar cita: {str(e)}"
        )


@router.get(
    "",
    response_model=CitaListResponse,
    summary="Listar citas con buscador y filtros",
    description="Obtiene la lista de consultas con soporte de búsqueda en tiempo real y filtros por fecha o estado."
)
def listar_citas(
    q: Optional[str] = Query(None, description="Término de búsqueda: paciente, CI, médico, especialidad"),
    fecha: Optional[date] = Query(None, description="Filtrar por fecha específica (YYYY-MM-DD)"),
    estado: Optional[str] = Query(None, description="Filtrar por estado: PENDIENTE, CONFIRMADA, COMPLETADA, CANCELADA"),
    id_medico: Optional[int] = Query(None, description="Filtrar por ID de médico"),
    id_paciente: Optional[int] = Query(None, description="Filtrar por ID de paciente"),
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=100, description="Cantidad de registros por página"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.listar_citas(
        db=db,
        q=q,
        fecha=fecha,
        estado=estado,
        id_medico=id_medico,
        id_paciente=id_paciente,
        page=page,
        page_size=page_size
    )


@router.get(
    "/horarios-disponibles",
    response_model=List[HorarioSlot],
    summary="Consultar horarios disponibles de un especialista",
    description="Retorna la lista de intervalos de tiempo indicando cuáles están libres y cuáles ocupados."
)
def obtener_horarios(
    id_medico: int = Query(..., description="ID del médico"),
    fecha: date = Query(..., description="Fecha a consultar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.obtener_horarios_disponibles(db, id_medico, fecha)


@router.get(
    "/{id_cita}",
    response_model=CitaResponse,
    summary="Obtener detalle de una cita",
    description="Devuelve la información completa de una cita por su identificador."
)
def obtener_cita(
    id_cita: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    cita = service.obtener_cita_por_id(db, id_cita)
    if not cita:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cita no encontrada"
        )
    return service.formatear_cita_response(cita)


@router.put(
    "/{id_cita}",
    response_model=CitaResponse,
    summary="Actualizar / Editar una cita en tiempo real",
    description="Permite modificar el paciente, especialista, fecha, horario o estado de una cita existente."
)
def actualizar_cita(
    id_cita: int,
    datos: CitaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    cita_actualizada = service.actualizar_cita(db, id_cita, datos)
    if not cita_actualizada:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cita no encontrada"
        )
    return cita_actualizada


@router.delete(
    "/{id_cita}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar una cita dinámicamente",
    description="Elimina una cita médica del sistema de manera instantánea."
)
def eliminar_cita(
    id_cita: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    eliminado = service.eliminar_cita(db, id_cita)
    if not eliminado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cita no encontrada o ya fue eliminada"
        )
    return {"message": "Cita eliminada exitosamente", "id_cita": id_cita}
