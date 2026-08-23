from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict, Field


class UsuarioBase(BaseModel):
    nombres: str = Field(..., min_length=2, max_length=100, examples=["Juan Carlos"])
    apellidos: str = Field(..., min_length=2, max_length=100, examples=["Pérez Gómez"])
    correo: EmailStr = Field(..., examples=["juan.perez@ejemplo.com"])
    telefono: Optional[str] = Field(None, max_length=20, examples=["+591 70000000"])
    foto_perfil: Optional[str] = Field(None, max_length=500, examples=["https://ejemplo.com/fotos/avatar.jpg"])
    notificaciones_push: Optional[bool] = True
    notificaciones_email: Optional[bool] = True
    notificaciones_sms: Optional[bool] = False


class UsuarioCreate(UsuarioBase):
    password: str = Field(..., min_length=6, max_length=100, examples=["PasswordSegura123"])


class UsuarioResponse(BaseModel):
    id_usuario: int
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
    fecha_actualizacion: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    correo: EmailStr = Field(..., examples=["juan.perez@ejemplo.com"])
    password: str = Field(..., examples=["PasswordSegura123"])


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."])
