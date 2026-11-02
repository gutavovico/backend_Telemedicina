"""API CU17. La autorización clínica y las transacciones viven en el servicio."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.prescriptions.router import _client_ip
from app.modules.medical_records.tratamientos import schemas, service


router = APIRouter(prefix="/api/v1/tratamientos", tags=["Tratamientos médicos (CU17)"])


async def treatment_error_handler(request: Request, exc: service.TreatmentError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})


@router.post("", status_code=201)
def crear_plan(payload: schemas.PlanCreate, request: Request, db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    return service.crear_plan(db, user, user.id_clinica, payload, _client_ip(request))


@router.get("")
def listar_planes(request: Request, estado: Optional[str] = None, id_paciente: Optional[int] = Query(default=None, gt=0),
                  skip: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
                  db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.listar_planes(db, user, user.id_clinica, estado, id_paciente, skip, limit, client_ip=_client_ip(request))


@router.post("/dosis/{id_dosis}/intentos", response_model=schemas.IdempotenciaDosisResponse)
def iniciar_intento_dosis(id_dosis: int, payload: schemas.IntentoDosisCreate, request: Request,
                          idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
                          db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    key = idempotency_key or request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
    return service.iniciar_intento_dosis(db, user, user.id_clinica, id_dosis, key, payload.request_hash, _client_ip(request))


@router.post("/dosis/{id_dosis}/registros")
def registrar_dosis(id_dosis: int, payload: schemas.RegistroDosis, request: Request,
                    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
                    db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.registrar_dosis(db, user, user.id_clinica, id_dosis, payload, idempotency_key, _client_ip(request))


@router.post("/dosis/{id_dosis}/registros/idempotencia/{idempotency_key}/resolver", response_model=schemas.IdempotenciaDosisResponse)
def resolver_operacion_abandonada(id_dosis: int, idempotency_key: str, request: Request,
                                  db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.resolver_operacion_abandonada(db, user, user.id_clinica, id_dosis, idempotency_key, _client_ip(request))


@router.get("/dosis/{id_dosis}/registros/idempotencia/{idempotency_key}", response_model=schemas.IdempotenciaDosisResponse)
@router.get("/dosis/{id_dosis}/registros/idempotencia", response_model=schemas.IdempotenciaDosisResponse, include_in_schema=False)
@router.get("/dosis/{id_dosis}/registros/idempotencia/", response_model=schemas.IdempotenciaDosisResponse, include_in_schema=False)
def consultar_idempotencia_dosis(id_dosis: int, request: Request, idempotency_key: str = "",
                                 db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.consultar_idempotencia_dosis(db, user, user.id_clinica, id_dosis, idempotency_key, _client_ip(request))


@router.get("/{id_tratamiento}")
def obtener_plan(id_tratamiento: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.obtener_plan(db, user, user.id_clinica, id_tratamiento, client_ip=_client_ip(request))


@router.get("/{id_tratamiento}/cronograma")
def cronograma(id_tratamiento: int, fecha: date, request: Request, db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    return service.cronograma(db, user, user.id_clinica, id_tratamiento, fecha, client_ip=_client_ip(request))


@router.get("/{id_tratamiento}/adherencia")
def adherencia(id_tratamiento: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.adherencia_plan(db, user, user.id_clinica, id_tratamiento, client_ip=_client_ip(request))


@router.post("/{id_tratamiento}/evoluciones", status_code=201)
def evolucion(id_tratamiento: int, payload: schemas.EvolucionCreate, request: Request,
              db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.evolucion(db, user, user.id_clinica, id_tratamiento, payload, _client_ip(request))


@router.post("/{id_tratamiento}/medicamentos/{id_medicamento_plan}/suspender")
def suspender(id_tratamiento: int, id_medicamento_plan: int, payload: schemas.MotivoClinico,
              request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.cambiar_medicamento(db, user, user.id_clinica, id_tratamiento,
                                      id_medicamento_plan, "suspender", payload, _client_ip(request))


@router.post("/{id_tratamiento}/medicamentos/{id_medicamento_plan}/reactivar")
def reactivar(id_tratamiento: int, id_medicamento_plan: int, payload: schemas.MotivoClinico,
              request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.cambiar_medicamento(db, user, user.id_clinica, id_tratamiento,
                                      id_medicamento_plan, "reactivar", payload, _client_ip(request))


@router.patch("/{id_tratamiento}/vigencia")
def prorrogar(id_tratamiento: int, payload: schemas.VigenciaUpdate, request: Request,
              db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.prorrogar(db, user, user.id_clinica, id_tratamiento, payload, _client_ip(request))


@router.post("/{id_tratamiento}/finalizar")
def finalizar(id_tratamiento: int, payload: schemas.MotivoClinico, request: Request,
              db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return service.finalizar(db, user, user.id_clinica, id_tratamiento, payload, _client_ip(request))
