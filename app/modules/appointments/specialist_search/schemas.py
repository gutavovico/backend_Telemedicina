from datetime import date, time
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class EspecialidadOut(BaseModel):
    id_especialidad: int
    nombre: str
    es_principal: bool = False

    model_config = ConfigDict(from_attributes=True)


class ServicioOut(BaseModel):
    id_servicio: int
    nombre: str
    descripcion: Optional[str] = None
    modalidad: str
    costo: float
    moneda: str = "BOB"
    duracion_minutos: int
    hora_inicio: str
    hora_fin: str

    model_config = ConfigDict(from_attributes=True)


class SlotDisponibilidad(BaseModel):
    hora_inicio: str
    hora_fin: str
    disponible: bool


class DiaDisponibilidad(BaseModel):
    fecha: str
    slots: List[SlotDisponibilidad] = Field(default_factory=list)


class EspecialistaItem(BaseModel):
    id_medico: int
    nombre_completo: str
    foto_url: Optional[str] = None
    matricula_profesional: str
    descripcion_profesional: Optional[str] = None
    experiencia: Optional[str] = None
    especialidades: List[EspecialidadOut] = Field(default_factory=list)
    servicios: List[ServicioOut] = Field(default_factory=list)
    disponibilidad: List[DiaDisponibilidad] = Field(default_factory=list)


class BusquedaEspecialistasResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[EspecialistaItem]


class EspecialistaDisponibilidadResponse(BaseModel):
    id_medico: int
    nombre_completo: str
    foto_url: Optional[str] = None
    matricula_profesional: str
    descripcion_profesional: Optional[str] = None
    experiencia: Optional[str] = None
    especialidades: List[EspecialidadOut] = Field(default_factory=list)
    servicios: List[ServicioOut] = Field(default_factory=list)
    disponibilidad: List[DiaDisponibilidad] = Field(default_factory=list)

