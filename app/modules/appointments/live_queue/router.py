from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.appointments.agenda.schemas import BloqueoResponse
from app.modules.auth.dependencies import get_required_tenant_id, require_roles
from app.modules.auth.models import Usuario
from . import service
from .schemas import (
    ColaOperativaResponse,
    MiTurnoResponse,
    PausaCreate,
)
from .service import hoy_cola

router = APIRouter(prefix="/cola", tags=["Fila virtual (CU08)"])
Db = Annotated[Session, Depends(get_db)]
Tenant = Annotated[int, Depends(get_required_tenant_id)]
Staff = Annotated[Usuario, Depends(require_roles(["MEDICO", "MÉDICO", "RECEPCION", "RECEPCIÓN"]))]
Paciente = Annotated[Usuario, Depends(require_roles(["PACIENTE"]))]


@router.get("/mi-turno", response_model=MiTurnoResponse)
def get_mi_turno(db: Db, user: Paciente, tenant_id: Tenant):
    return service.mi_turno(db, user, tenant_id)


@router.get("", response_model=ColaOperativaResponse)
def get_cola(
    db: Db,
    user: Staff,
    tenant_id: Tenant,
    fecha: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    id_medico: int | None = Query(None, gt=0),
):
    dia = date.fromisoformat(fecha) if fecha else hoy_cola()
    return service.ver_cola(db, user, tenant_id, id_medico, dia)


@router.post("/{id_cita}/avanzar", response_model=ColaOperativaResponse)
def post_avanzar(id_cita: int, db: Db, user: Staff, tenant_id: Tenant):
    return service.avanzar(db, user, tenant_id, id_cita)


@router.post("/{id_cita}/perdida", response_model=ColaOperativaResponse)
def post_perdida(id_cita: int, db: Db, user: Staff, tenant_id: Tenant):
    return service.marcar_perdida(db, user, tenant_id, id_cita)


@router.post("/pausas", response_model=BloqueoResponse, status_code=201)
def post_pausa(datos: PausaCreate, db: Db, user: Staff, tenant_id: Tenant):
    return service.registrar_pausa(db, user, tenant_id, datos)
