from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medicos import service
from app.modules.medicos.schemas import (
    AsignacionEspecialidad,
    EspecialidadCreate,
    EspecialidadResponse,
    EspecialidadUpdate,
    EstadoUpdate,
    MedicoCreate,
    MedicoListResponse,
    MedicoResponse,
    MedicoUpdate,
)

router = APIRouter(prefix="/medicos", tags=["Médicos (CU04)"])
router_especialidades = APIRouter(prefix="/especialidades", tags=["Especialidades (CU04)"])


# ---------------------------------------------------------------------------
# Médicos — endpoints propios
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=MedicoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear perfil profesional de médico",
    description="Crea el perfil profesional (matrícula, descripción, especialidades) "
                "para un usuario ya registrado. Relación 1:1 usuario-médico (CU04).",
)
def crear_medico(
    datos: MedicoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.crear_medico(db, datos)


@router.get(
    "/me",
    response_model=MedicoResponse,
    summary="Obtener mi perfil médico",
    description="Devuelve el perfil profesional del médico autenticado (según su token JWT).",
)
def obtener_mi_perfil(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.obtener_medico_por_usuario(db, current_user.id_usuario)


@router.get(
    "",
    response_model=MedicoListResponse,
    summary="Listar médicos",
    description="Lista médicos con filtros opcionales por nombre, especialidad y estado, "
                "con paginación. Por defecto solo muestra activos.",
)
def listar_medicos(
    nombre: Optional[str] = Query(None, max_length=100, description="Busca por nombres, apellidos o correo del usuario"),
    id_especialidad: Optional[int] = Query(None, gt=0, description="Filtra por especialidad"),
    estado: Optional[str] = Query(None, pattern="^(activo|inactivo)$", description="Por defecto: activo"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    total, items = service.listar_medicos(
        db,
        nombre=nombre,
        id_especialidad=id_especialidad,
        estado=estado,
        skip=skip,
        limit=limit,
    )
    return MedicoListResponse(total=total, items=items)


@router.get(
    "/{id_medico}",
    response_model=MedicoResponse,
    summary="Obtener médico por id",
    description="Devuelve el perfil profesional completo, con datos del usuario y especialidades.",
)
def obtener_medico(
    id_medico: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.obtener_medico(db, id_medico)


@router.put(
    "/{id_medico}",
    response_model=MedicoResponse,
    summary="Actualizar perfil médico",
    description="Actualiza datos profesionales: matrícula, descripción, experiencia y foto.",
)
def actualizar_medico(
    id_medico: int,
    datos: MedicoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.actualizar_medico(db, id_medico, datos)


@router.patch(
    "/{id_medico}/estado",
    response_model=MedicoResponse,
    summary="Activar o desactivar médico",
    description="Cambia el estado del perfil médico (borrado lógico): 'activo' o 'inactivo'.",
)
def cambiar_estado(
    id_medico: int,
    datos: EstadoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.cambiar_estado_medico(db, id_medico, datos.nuevo_estado)


@router.post(
    "/{id_medico}/especialidades",
    response_model=MedicoResponse,
    summary="Asignar especialidad a médico",
    description="Asigna una especialidad al médico. Si es_principal=true, desmarca la "
                "especialidad principal anterior (solo se permite una principal).",
)
def asignar_especialidad(
    id_medico: int,
    datos: AsignacionEspecialidad,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.asignar_especialidad(db, id_medico, datos)


@router.delete(
    "/{id_medico}/especialidades/{id_especialidad}",
    response_model=MedicoResponse,
    summary="Quitar especialidad a médico",
    description="Quita una especialidad asignada al médico.",
)
def quitar_especialidad(
    id_medico: int,
    id_especialidad: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.quitar_especialidad(db, id_medico, id_especialidad)


# ---------------------------------------------------------------------------
# Catálogo de especialidades
# ---------------------------------------------------------------------------

@router_especialidades.get(
    "",
    response_model=List[EspecialidadResponse],
    summary="Listar especialidades",
    description="Devuelve el catálogo de especialidades. Parámetro todos=true incluye inactivas.",
)
def listar_especialidades(
    todos: bool = Query(False, description="Incluir especialidades inactivas"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.listar_especialidades(db, solo_activas=not todos)


@router_especialidades.post(
    "",
    response_model=EspecialidadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear especialidad",
    description="Crea una nueva especialidad en el catálogo. El nombre debe ser único.",
)
def crear_especialidad(
    datos: EspecialidadCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.crear_especialidad(db, datos)


@router_especialidades.put(
    "/{id_especialidad}",
    response_model=EspecialidadResponse,
    summary="Actualizar especialidad",
    description="Actualiza nombre, descripción o estado de una especialidad.",
)
def actualizar_especialidad(
    id_especialidad: int,
    datos: EspecialidadUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.actualizar_especialidad(db, id_especialidad, datos)


@router_especialidades.delete(
    "/{id_especialidad}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar especialidad",
    description="Elimina una especialidad del catálogo. Falla con 409 si tiene médicos asignados.",
)
def eliminar_especialidad(
    id_especialidad: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    service.eliminar_especialidad(db, id_especialidad)
    return None
