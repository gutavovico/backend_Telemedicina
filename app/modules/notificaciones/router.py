"""Registro de dispositivos push (CU19).

Reutiliza la tabla `tratamiento_dispositivos` y el cifrado de tokens de CU17,
pero expone endpoints genéricos para que la app móvil registre el token FCM
sin depender de los permisos de tratamientos.
"""
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.tratamientos import avisos
from app.modules.medical_records.tratamientos.avisos_models import TratamientoDispositivo

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones push (CU19)"])


class DispositivoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=4096)
    plataforma: Literal["ANDROID", "IOS"] = "ANDROID"

    @field_validator("token")
    @classmethod
    def validar_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El token no puede estar vacío")
        return value


def _clinica(user: Usuario, tenant_id: int | None) -> int:
    id_clinica = tenant_id or user.id_clinica
    if id_clinica is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="No se pudo determinar la clínica")
    return int(id_clinica)


@router.post("/dispositivos", status_code=201, summary="Registrar token FCM del móvil")
def registrar_dispositivo(
    payload: DispositivoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    tenant_id: int | None = Depends(get_current_tenant_id),
):
    from fastapi import HTTPException

    if (user.estado or "").upper() != "ACTIVO":
        raise HTTPException(status_code=403, detail="Usuario no activo")
    if not user.notificaciones_push:
        raise HTTPException(status_code=403, detail="Notificaciones push desactivadas")
    if not avisos.push_configurado():
        raise HTTPException(status_code=503, detail="Proveedor push no configurado")

    id_clinica = _clinica(user, tenant_id)
    token_hash = avisos.hash_token(payload.token)
    item = db.execute(
        select(TratamientoDispositivo)
        .where(
            TratamientoDispositivo.id_clinica == id_clinica,
            TratamientoDispositivo.id_usuario == user.id_usuario,
            TratamientoDispositivo.token_hash == token_hash,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if item is None:
        item = TratamientoDispositivo(
            id_clinica=id_clinica,
            id_usuario=user.id_usuario,
            token_hash=token_hash,
            token_cifrado=avisos.cifrar_token(payload.token),
            plataforma=payload.plataforma,
            activo=True,
        )
        db.add(item)
    else:
        item.activo = True
        item.plataforma = payload.plataforma
        item.token_cifrado = avisos.cifrar_token(payload.token)

    db.commit()
    db.refresh(item)
    return {"id_dispositivo": item.id_dispositivo, "plataforma": item.plataforma}


@router.delete("/dispositivos/{id_dispositivo}", status_code=204)
def revocar_dispositivo(
    id_dispositivo: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    tenant_id: int | None = Depends(get_current_tenant_id),
):
    from fastapi import HTTPException

    id_clinica = _clinica(user, tenant_id)
    item = db.execute(
        select(TratamientoDispositivo).where(
            TratamientoDispositivo.id_dispositivo == id_dispositivo,
            TratamientoDispositivo.id_clinica == id_clinica,
            TratamientoDispositivo.id_usuario == user.id_usuario,
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    item.activo = False
    db.commit()
    return Response(status_code=204)
