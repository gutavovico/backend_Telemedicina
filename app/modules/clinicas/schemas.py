from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ClinicaItemResponse(BaseModel):
    clinica_id: int
    nombre: str
    razon_social: Optional[str] = None
    nit: Optional[str] = None
    estado: str
    usuarios_activos: int = 0
    fecha_creacion: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ClinicaListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[ClinicaItemResponse]


class ClinicaEstadoUpdate(BaseModel):
    estado: str = Field(..., pattern="^(ACTIVO|INACTIVO|SUSPENDIDO)$")


class ClinicaEstadoResponse(BaseModel):
    clinica_id: int
    nombre: str
    estado: str
    mensaje: str = "Estado actualizado correctamente"
