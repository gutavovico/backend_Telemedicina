"""Entradas de la API CU17 alineadas con el contrato local."""
from datetime import date, datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MedicamentoPlanCreate(StrictInput):
    id_receta_detalle: int = Field(gt=0)
    fecha_inicio: date
    fecha_fin: date
    horas_locales: list[str] = Field(min_length=1, max_length=24)
    indicaciones: str | None = Field(default=None, max_length=4000)

    @field_validator("horas_locales")
    @classmethod
    def validar_horas(cls, value):
        if any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", h) for h in value):
            raise ValueError("Cada hora debe tener formato HH:mm")
        if value != sorted(set(value)):
            raise ValueError("Las horas deben ser únicas y estar ordenadas")
        return value

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final precede al inicio")
        if (self.fecha_fin - self.fecha_inicio).days >= 366:
            raise ValueError("El rango inicial del medicamento no puede superar 366 días")
        return self


class PlanCreate(StrictInput):
    id_consulta: int = Field(gt=0)
    id_receta: int | None = Field(default=None, gt=0)
    id_diagnostico: int | None = Field(default=None, gt=0)
    fecha_inicio: date
    fecha_fin: date
    zona_horaria: str = Field(min_length=1, max_length=100)
    notas: str | None = Field(default=None, max_length=4000)
    medicamentos: list[MedicamentoPlanCreate] = Field(default_factory=list)

    @field_validator("zona_horaria")
    @classmethod
    def validar_zona(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Zona horaria IANA inválida")
        return value

    @model_validator(mode="after")
    def validar_plan(self):
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final precede al inicio")
        if (self.fecha_fin - self.fecha_inicio).days >= 366:
            raise ValueError("El rango inicial del plan no puede superar 366 días")
        if self.id_receta is None and self.medicamentos:
            raise ValueError("Un plan sin receta no admite medicamentos")
        if self.id_receta is not None and not self.medicamentos:
            raise ValueError("La receta requiere medicamentos con horarios confirmados")
        if len({m.id_receta_detalle for m in self.medicamentos}) != len(self.medicamentos):
            raise ValueError("No se permiten detalles duplicados")
        if any(m.fecha_inicio < self.fecha_inicio or m.fecha_fin > self.fecha_fin for m in self.medicamentos):
            raise ValueError("Las fechas del medicamento deben estar dentro del plan")
        return self


class RegistroDosis(StrictInput):
    estado: Literal["INGERIDA", "OMITIDA", "POSPUESTA"]
    efectiva_en: datetime | None = None
    nota: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validar_ingesta(self):
        if self.estado == "INGERIDA":
            if self.efectiva_en is None or self.efectiva_en.utcoffset() is None:
                raise ValueError("La ingesta exige fecha y hora con zona")
        elif self.efectiva_en is not None:
            raise ValueError("Solo una ingesta admite hora efectiva")
        return self


class IntentoDosisCreate(BaseModel):
    request_hash: str


class IdempotenciaDosisResponse(BaseModel):
    id_dosis: int
    idempotency_key: str
    estado: str  # 'CONFIRMADA', 'EN_CURSO', 'RECHAZADA', 'NO_INICIADA'
    confirmado: bool
    en_curso: bool
    rechazado: bool
    dosis: Optional[dict] = None
    mensaje: Optional[str] = None
    generacion: Optional[int] = 1



class EvolucionCreate(StrictInput):
    nota: str = Field(min_length=10, max_length=4000)


class MotivoClinico(StrictInput):
    motivo: str = Field(min_length=10, max_length=1000)


class MedicamentoVigencia(StrictInput):
    id_medicamento_plan: int = Field(gt=0)
    fecha_fin: date


class VigenciaUpdate(MotivoClinico):
    fecha_fin: date
    medicamentos: list[MedicamentoVigencia] = Field(default_factory=list)

    @model_validator(mode="after")
    def sin_duplicados(self):
        if len({m.id_medicamento_plan for m in self.medicamentos}) != len(self.medicamentos):
            raise ValueError("No se permiten medicamentos duplicados")
        return self
