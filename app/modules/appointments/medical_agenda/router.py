from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, require_roles
from app.modules.auth.models import Usuario
from . import service
from .schemas import (
    AccionBloqueoResponse, BloqueoCreate, BloqueoResponse, DisponibilidadResponse,
    HorarioCreate, HorarioEstado, HorarioResponse, ServicioResponse,
)

router = APIRouter(prefix="/appointments/agenda", tags=["Agenda médica (CU05)"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[int | None, Depends(get_current_tenant_id)]
Actor = Annotated[Usuario, Depends(require_roles([
    "MEDICO", "MÉDICO", "RECEPCION", "RECEPCIÓN", "ADMIN", "ADMINISTRADOR",
    "ADMINISTRACION", "ADMINISTRACIÓN",
]))]


@router.get("/servicios", response_model=list[ServicioResponse])
def listar_servicios(db: Db, user: Actor, tenant_id: Tenant):
    return service.listar_servicios(db, user, tenant_id)


@router.get("/horarios", response_model=list[HorarioResponse])
def listar_horarios(db: Db, user: Actor, tenant_id: Tenant, id_medico: int | None = Query(None, gt=0)):
    return service.listar_horarios(db, user, tenant_id, id_medico)


@router.post("/horarios", response_model=HorarioResponse, status_code=201)
def crear_horario(datos: HorarioCreate, db: Db, user: Actor, tenant_id: Tenant):
    return service.crear_horario(db, datos, user, tenant_id)


@router.patch("/horarios/{id_horario}/estado", response_model=HorarioResponse)
def cambiar_horario(id_horario: int, datos: HorarioEstado, db: Db, user: Actor, tenant_id: Tenant):
    return service.cambiar_estado_horario(db, id_horario, datos.estado, user, tenant_id)


@router.get("/bloqueos", response_model=list[BloqueoResponse])
def listar_bloqueos(db: Db, user: Actor, tenant_id: Tenant, id_medico: int | None = Query(None, gt=0)):
    return service.listar_bloqueos(db, user, tenant_id, id_medico)


@router.post("/bloqueos", response_model=BloqueoResponse, status_code=201)
def crear_bloqueo(datos: BloqueoCreate, db: Db, user: Actor, tenant_id: Tenant):
    return service.crear_bloqueo(db, datos, user, tenant_id)


@router.patch("/bloqueos/{id_bloqueo}/aprobar", response_model=AccionBloqueoResponse)
def aprobar(id_bloqueo: int, db: Db, user: Actor, tenant_id: Tenant):
    return service.cambiar_bloqueo(db, id_bloqueo, "aprobar", user, tenant_id)


@router.patch("/bloqueos/{id_bloqueo}/rechazar", response_model=AccionBloqueoResponse)
def rechazar(id_bloqueo: int, db: Db, user: Actor, tenant_id: Tenant):
    return service.cambiar_bloqueo(db, id_bloqueo, "rechazar", user, tenant_id)


@router.patch("/bloqueos/{id_bloqueo}/liberar", response_model=AccionBloqueoResponse)
def liberar(id_bloqueo: int, db: Db, user: Actor, tenant_id: Tenant):
    return service.cambiar_bloqueo(db, id_bloqueo, "liberar", user, tenant_id)


@router.get("/disponibilidad", response_model=DisponibilidadResponse)
def disponibilidad(db: Db, user: Actor, tenant_id: Tenant, fecha: date,
                   id_medico: int = Query(..., gt=0), id_servicio: int = Query(..., gt=0)):
    return service.disponibilidad(db, user, tenant_id, id_medico, fecha, id_servicio)
