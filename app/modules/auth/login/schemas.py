from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UsuarioCreate(BaseModel):
    id_clinica: Optional[int] = None
    id_rol: Optional[int] = None
    nombres: str = Field(..., min_length=2, max_length=100)
    apellidos: str = Field(..., min_length=2, max_length=100)
    correo: EmailStr
    telefono: Optional[str] = Field(None, max_length=30)
    password: str = Field(..., min_length=6, max_length=100)
    foto_perfil: Optional[str] = Field(None, max_length=500)
    notificaciones_push: bool = True
    notificaciones_email: bool = True
    notificaciones_sms: bool = False


class UsuarioResponse(BaseModel):
    id_usuario: int
    id_clinica: Optional[int] = None
    tenant_id: Optional[str] = None
    id_rol: Optional[int] = None
    nombres: str
    apellidos: str
    correo: str
    telefono: Optional[str] = None
    foto_perfil: Optional[str] = None
    estado: str
    notificaciones_push: bool
    notificaciones_email: bool
    notificaciones_sms: bool
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    correo: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str
