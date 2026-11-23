"""Esquemas Pydantic v2 para CU20: Notificaciones y Recordatorios Multicanal."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class WebPushConfigDTO(BaseModel):
    public_key: str
    habilitado: bool = True


class WebPushKeysDTO(BaseModel):
    p256dh: str = Field(..., min_length=10)
    auth: str = Field(..., min_length=8)


class WebPushSubscripcionDTO(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=2048)
    keys: WebPushKeysDTO
    dispositivo_id: Optional[str] = Field(default=None, max_length=64)


class RegistroDispositivoDTO(BaseModel):
    dispositivo_id: str = Field(..., min_length=4, max_length=64)
    canal: Literal["PWA", "FLUTTER"]
    push_token: Optional[str] = Field(default=None, max_length=4096)


class DispositivoDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_dispositivo: int
    id_clinica: Optional[int] = None
    id_usuario: int
    rol_usuario: Optional[str] = None
    canal: str
    dispositivo_id: str
    estado: str
    revision: int
    creado_en: datetime
    revocado_en: Optional[datetime] = None


class NotificacionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_notificacion: int
    id_clinica: Optional[int] = None
    id_usuario: int
    outbox_id: Optional[int] = None
    rol_destinatario: Optional[str] = None
    tipo: Optional[str] = None
    categoria: str = "SISTEMA"
    canal: Optional[str] = None
    canal_badge: Optional[str] = None
    titulo: Optional[str] = None
    mensaje: Optional[str] = None
    recurso_tipo: Optional[str] = None
    recurso_id: Optional[str] = None
    enlace_accion: Optional[str] = None
    payload_extra: Optional[Dict[str, Any]] = None
    fecha_programada: Optional[datetime] = None
    fecha_envio: Optional[datetime] = None
    fecha_lectura: Optional[datetime] = None
    estado: str
    created_at: datetime


class NotificacionResumenDTO(BaseModel):
    no_leidas: int
    total: int
    por_categoria: Dict[str, int] = Field(default_factory=dict)


class EmisionNotificacionCommand(BaseModel):
    id_usuario: Optional[int] = None
    tipo: str = Field(..., min_length=2, max_length=50)
    titulo: str = Field(..., min_length=2, max_length=200)
    mensaje: str = Field(..., min_length=2, max_length=2000)
    canal_objetivo: Literal["MULTI", "PUSH", "EMAIL", "SMS"] = "MULTI"
    canal_badge: Optional[str] = None
    recurso_tipo: Optional[str] = None
    recurso_id: Optional[str] = None
    enlace_accion: Optional[str] = None
    fecha_programada: Optional[datetime] = None
    idempotency_key: Optional[str] = None
    payload_extra: Optional[Dict[str, Any]] = None


class PreferenciasNotificacionDTO(BaseModel):
    notificaciones_push: bool
    notificaciones_email: bool
    notificaciones_sms: bool


class PreferenciasNotificacionUpdateDTO(BaseModel):
    notificaciones_push: Optional[bool] = None
    notificaciones_email: Optional[bool] = None
    notificaciones_sms: Optional[bool] = None


class ProcesarOutboxResumenDTO(BaseModel):
    procesados: int
    enviados: int
    reintentos: int
    fallidos: int
    sin_destinos: int


class MarcarTodasLeidasDTO(BaseModel):
    actualizadas: int
