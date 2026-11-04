"""Bandeja de avisos y registro seguro de dispositivos del paciente."""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.tratamientos import avisos, service
from app.modules.medical_records.tratamientos.avisos_models import TratamientoAviso, TratamientoDispositivo
from app.modules.medical_records.tratamientos.models import Tratamiento


router = APIRouter(prefix="/api/v1/tratamientos", tags=["Tratamientos - avisos (CU17)"])


class DispositivoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=4096)
    plataforma: Literal["ANDROID", "IOS"]

    @field_validator("token")
    @classmethod
    def validar_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El token no puede estar vacío")
        return value


def _contexto(db: Session, user: Usuario, tenant_id: int | None):
    return service.authorize(db, user, tenant_id, "treatments:notify:read")


def _serializar(aviso: TratamientoAviso) -> dict:
    def iso(value):
        return service.as_utc(value).isoformat().replace("+00:00", "Z") if value else None
    return {"id_aviso": aviso.id_aviso, "id_tratamiento": aviso.id_tratamiento,
            "id_dosis": aviso.id_dosis, "tipo": aviso.tipo, "canal": aviso.canal,
            "titulo": aviso.titulo, "mensaje": aviso.mensaje, "estado": aviso.estado,
            "programada_en": iso(aviso.programada_en_utc), "enviada_en": iso(aviso.enviada_en_utc),
            "leida_en": iso(aviso.leida_en_utc)}


def _consulta_avisos(db: Session, user: Usuario, tenant_id: int, role: str, profile_id: int):
    statement = select(TratamientoAviso).join(
        Tratamiento, (Tratamiento.id_tratamiento == TratamientoAviso.id_tratamiento) &
        (Tratamiento.id_clinica == TratamientoAviso.id_clinica)
    ).where(TratamientoAviso.id_clinica == tenant_id,
            TratamientoAviso.id_usuario == user.id_usuario, TratamientoAviso.canal == "WEB")
    return statement.where(Tratamiento.id_paciente == profile_id) if role == "PACIENTE" else statement.where(
        Tratamiento.id_medico == profile_id)


@router.get("/avisos")
def listar_avisos(skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                  no_leidos: bool = False, db: Session = Depends(get_db),
                  user: Usuario = Depends(get_current_user),
                  tenant_id: int | None = Depends(get_current_tenant_id)):
    role, profile_id = _contexto(db, user, tenant_id)
    query = _consulta_avisos(db, user, tenant_id, role, profile_id)
    if no_leidos:
        query = query.where(TratamientoAviso.leida_en_utc.is_(None))
    from sqlalchemy import func
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    items = db.execute(query.order_by(TratamientoAviso.created_at.desc(), TratamientoAviso.id_aviso.desc())
                       .offset(skip).limit(limit)).scalars().all()
    return {"items": [_serializar(item) for item in items], "total": total}


@router.patch("/avisos/{id_aviso}/leer")
def leer_aviso(id_aviso: int, db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user),
               tenant_id: int | None = Depends(get_current_tenant_id)):
    role, profile_id = _contexto(db, user, tenant_id)
    item = db.execute(_consulta_avisos(db, user, tenant_id, role, profile_id).where(
        TratamientoAviso.id_aviso == id_aviso).with_for_update()).scalar_one_or_none()
    if item is None:
        raise service.TreatmentError(404, "Aviso no encontrado", "TREATMENT_NOT_FOUND")
    if item.leida_en_utc is None:
        item.leida_en_utc = service.now_utc()
        # La lectura confirma entrega de la bandeja web.
        item.estado = "ENVIADO"
        item.enviada_en_utc = item.leida_en_utc
        db.commit()
        db.refresh(item)
    return _serializar(item)


@router.post("/dispositivos", status_code=201)
def registrar_dispositivo(payload: DispositivoCreate, db: Session = Depends(get_db),
                          user: Usuario = Depends(get_current_user),
                          tenant_id: int | None = Depends(get_current_tenant_id)):
    role, _ = _contexto(db, user, tenant_id)
    if role != "PACIENTE" or not user.notificaciones_push:
        raise service.TreatmentError(403, "Notificaciones push no autorizadas", "TREATMENT_FORBIDDEN")
    if not avisos.push_configurado():
        raise service.TreatmentError(503, "Proveedor push no configurado", "TREATMENT_DELIVERY_UNAVAILABLE")
    token_hash = avisos.hash_token(payload.token)
    item = db.execute(select(TratamientoDispositivo).where(
        TratamientoDispositivo.id_clinica == tenant_id,
        TratamientoDispositivo.id_usuario == user.id_usuario,
        TratamientoDispositivo.token_hash == token_hash).with_for_update()).scalar_one_or_none()
    if item is None:
        item = TratamientoDispositivo(id_clinica=tenant_id, id_usuario=user.id_usuario,
                                     token_hash=token_hash, token_cifrado=avisos.cifrar_token(payload.token),
                                     plataforma=payload.plataforma, activo=True)
        db.add(item)
    else:
        item.activo = True
        item.plataforma = payload.plataforma
        item.token_cifrado = avisos.cifrar_token(payload.token)
    db.commit()
    db.refresh(item)
    return {"id_dispositivo": item.id_dispositivo, "plataforma": item.plataforma}


@router.delete("/dispositivos/{id_dispositivo}", status_code=204)
def revocar_dispositivo(id_dispositivo: int, db: Session = Depends(get_db),
                        user: Usuario = Depends(get_current_user),
                        tenant_id: int | None = Depends(get_current_tenant_id)):
    role, _ = _contexto(db, user, tenant_id)
    if role != "PACIENTE":
        raise service.TreatmentError(403, "Permiso denegado", "TREATMENT_FORBIDDEN")
    item = db.execute(select(TratamientoDispositivo).where(
        TratamientoDispositivo.id_dispositivo == id_dispositivo,
        TratamientoDispositivo.id_clinica == tenant_id,
        TratamientoDispositivo.id_usuario == user.id_usuario)).scalar_one_or_none()
    if item is None:
        raise service.TreatmentError(404, "Dispositivo no encontrado", "TREATMENT_NOT_FOUND")
    item.activo = False
    db.commit()
    return Response(status_code=204)
