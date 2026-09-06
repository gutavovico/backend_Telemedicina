from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user, require_admin
from app.modules.auth.models import Usuario
from app.modules.appointments.doctor_profile import service
from app.modules.appointments.doctor_profile.schemas import (
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


@router.post(
    "",
    response_model=MedicoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear perfil profesional de médico",
)
def crear_medico(
    datos: MedicoCreate,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return service.crear_medico(db, datos, current_tenant_id=tenant_id)


@router.get(
    "/me",
    response_model=MedicoResponse,
    summary="Obtener mi perfil médico",
)
def obtener_mi_perfil(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return service.obtener_medico_por_usuario(db, current_user.id_usuario, current_tenant_id=tenant_id)


@router.get(
    "",
    response_model=MedicoListResponse,
    summary="Listar médicos",
)
def listar_medicos(
    nombre: Optional[str] = Query(None, max_length=100),
    id_especialidad: Optional[int] = Query(None, gt=0),
    estado: Optional[str] = Query(None, pattern="^(activo|inactivo)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    total, items = service.listar_medicos(
        db,
        nombre=nombre,
        id_especialidad=id_especialidad,
        estado=estado,
        skip=skip,
        limit=limit,
        current_tenant_id=tenant_id,
    )
    return MedicoListResponse(total=total, items=items)


@router.get(
    "/{id_medico}",
    response_model=MedicoResponse,
    summary="Obtener médico por id",
)
def obtener_medico(
    id_medico: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return service.obtener_medico(db, id_medico, current_tenant_id=tenant_id)


@router.put(
    "/{id_medico}",
    response_model=MedicoResponse,
    summary="Actualizar perfil médico",
)
def actualizar_medico(
    id_medico: int,
    datos: MedicoUpdate,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return service.actualizar_medico(db, id_medico, datos, current_tenant_id=tenant_id)


@router.patch(
    "/{id_medico}/estado",
    response_model=MedicoResponse,
    summary="Activar o desactivar médico",
)
def cambiar_estado(
    id_medico: int,
    datos: EstadoUpdate,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return service.cambiar_estado_medico(db, id_medico, datos.nuevo_estado, current_tenant_id=tenant_id)


@router.post(
    "/{id_medico}/especialidades",
    response_model=MedicoResponse,
    summary="Asignar especialidad a médico",
)
def asignar_especialidad(
    id_medico: int,
    datos: AsignacionEspecialidad,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return service.asignar_especialidad(db, id_medico, datos, current_tenant_id=tenant_id)


@router.delete(
    "/{id_medico}/especialidades/{id_especialidad}",
    response_model=MedicoResponse,
    summary="Quitar especialidad a médico",
)
def quitar_especialidad(
    id_medico: int,
    id_especialidad: int,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return service.quitar_especialidad(db, id_medico, id_especialidad, current_tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# Especialidades
# ---------------------------------------------------------------------------

@router_especialidades.get(
    "",
    response_model=List[EspecialidadResponse],
    summary="Listar especialidades",
)
def listar_especialidades(
    todos: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.listar_especialidades(db, solo_activas=not todos)


@router_especialidades.post(
    "",
    response_model=EspecialidadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear especialidad",
)
def crear_especialidad(
    datos: EspecialidadCreate,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
):
    return service.crear_especialidad(db, datos)


@router_especialidades.put(
    "/{id_especialidad}",
    response_model=EspecialidadResponse,
    summary="Actualizar especialidad",
)
def actualizar_especialidad(
    id_especialidad: int,
    datos: EspecialidadUpdate,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
):
    return service.actualizar_especialidad(db, id_especialidad, datos)


@router_especialidades.delete(
    "/{id_especialidad}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar especialidad",
)
def eliminar_especialidad(
    id_especialidad: int,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
):
    service.eliminar_especialidad(db, id_especialidad)
    return None
