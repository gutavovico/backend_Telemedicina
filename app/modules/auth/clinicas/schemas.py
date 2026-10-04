from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClinicaItemResponse(BaseModel):
    clinica_id: int
    nombre: str
    razon_social: Optional[str] = None
    nit: Optional[str] = None
    estado: str
    usuarios_activos: int = 0
    admin_nombre: Optional[str] = None
    admin_correo: Optional[str] = None
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


class ClinicaSummary(BaseModel):
    id_clinica: int
    nombre: str
    estado: str


class AdminSummary(BaseModel):
    id_usuario: int
    correo: str


class ClinicaRegistroRequest(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=150)
    razon_social: Optional[str] = Field(None, max_length=200)
    nit: Optional[str] = Field(None, max_length=50)
    telefono: Optional[str] = Field(None, max_length=30)
    direccion: Optional[str] = Field(None, max_length=250)
    admin_nombres: str = Field(..., min_length=1, max_length=100)
    admin_apellidos: str = Field(..., min_length=1, max_length=100)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=6, max_length=100)


class ClinicaRegistroResponse(BaseModel):
    clinica: ClinicaSummary
    administrador: AdminSummary
