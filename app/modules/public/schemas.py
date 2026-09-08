from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClinicaRegistroRequest(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=150)
    razon_social: Optional[str] = Field(None, max_length=200)
    nit: Optional[str] = Field(None, max_length=50)
    telefono: Optional[str] = Field(None, max_length=30)
    direccion: Optional[str] = Field(None, max_length=250)
    admin_nombres: str = Field(..., min_length=2, max_length=100)
    admin_apellidos: str = Field(..., min_length=2, max_length=100)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=6, max_length=100)


class ClinicaSummary(BaseModel):
    id_clinica: int
    nombre: str
    estado: str

    model_config = ConfigDict(from_attributes=True)


class AdminSummary(BaseModel):
    id_usuario: int
    correo: str

    model_config = ConfigDict(from_attributes=True)


class ClinicaRegistroResponse(BaseModel):
    clinica: ClinicaSummary
    administrador: AdminSummary
