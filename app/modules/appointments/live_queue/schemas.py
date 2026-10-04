"""Contratos Pydantic v2 CU08 (derivan de openspec/contracts/live-queue.md)."""
from typing import Optional

from pydantic import BaseModel, Field


class MiTurnoResponse(BaseModel):
    id_cita: int
    hora: str
    estado: str
    posicion: int
    eta_minutos: int
    delante: int
    proximo: bool
    estado_cola: str
    mensaje_cola: Optional[str] = None
    medico_nombre: str
    fecha: str


class EntradaColaResponse(BaseModel):
    id_cita: int
    hora: str
    estado: str
    posicion: int
    eta_minutos: int
    paciente_nombre: str
    check_in: Optional[str] = None


class ColaOperativaResponse(BaseModel):
    id_medico: int
    medico_nombre: str
    fecha: str
    estado_cola: str
    mensaje_cola: Optional[str] = None
    duracion_promedio_min: int
    total_pendientes: int
    entradas: list[EntradaColaResponse]


class PausaCreate(BaseModel):
    id_medico: int = Field(..., gt=0)
    fecha: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    hora_inicio: str = Field(..., pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    hora_fin: str = Field(..., pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    motivo: str = Field(..., min_length=3, max_length=500)
