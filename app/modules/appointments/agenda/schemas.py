from datetime import date, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ServicioResponse(ResponseBase):
    id_servicio: int
    nombre: str
    descripcion: str | None
    hora_inicio: time
    hora_fin: time
    duracion_minutos: int
    costo: Decimal
    estado: str


class HorarioCreate(RequestBase):
    id_medico: int | None = Field(default=None, gt=0)
    id_servicio: int = Field(gt=0)
    dia_semana: int = Field(ge=1, le=7)


class HorarioEstado(RequestBase):
    estado: Literal["activo", "inactivo"]


class HorarioResponse(ResponseBase):
    id_horario: int
    id_medico: int
    id_servicio: int
    dia_semana: int
    estado: str


class BloqueoCreate(RequestBase):
    id_medico: int | None = Field(default=None, gt=0)
    id_servicio: int = Field(gt=0)
    fecha: date
    hora_inicio: time
    hora_fin: time
    motivo: str = Field(min_length=1)

    @field_validator("motivo")
    @classmethod
    def motivo_no_vacio(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El motivo es obligatorio")
        return value.strip()

    @field_validator("hora_inicio", "hora_fin")
    @classmethod
    def hora_local(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("Utilice horas locales sin zona horaria")
        return value


class BloqueoResponse(ResponseBase):
    id_bloqueo: int
    id_medico: int
    id_servicio: int
    fecha: date
    hora_inicio: time
    hora_fin: time
    motivo: str
    estado: Literal["PENDIENTE", "APROBADO", "RECHAZADO", "LIBERADO"]


class AccionBloqueoResponse(BloqueoResponse):
    citas_afectadas: list[int] = Field(default_factory=list)
    notificaciones_creadas: int = 0
    advertencias: list[str] = Field(default_factory=list)


class SlotResponse(BaseModel):
    hora_inicio: time
    hora_fin: time
    disponible: bool


class DisponibilidadResponse(BaseModel):
    id_medico: int
    id_servicio: int
    fecha: date
    slots: list[SlotResponse]
    citas_verificadas: bool
    advertencias: list[str] = Field(default_factory=list)
