from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AdminUserBase(BaseModel):
    id_clinica: Optional[int] = Field(None, gt=0)
    tenant_id: Optional[str] = None
    id_rol: int = Field(..., gt=0)
    nombres: str = Field(..., min_length=2, max_length=100)
    apellidos: str = Field(..., min_length=2, max_length=100)
    correo: EmailStr
    telefono: Optional[str] = Field(None, max_length=30)
    foto_perfil: Optional[str] = Field(None, max_length=500)
    estado: str = Field(default="activo", min_length=1, max_length=20)
    notificaciones_push: bool = True
    notificaciones_email: bool = True
    notificaciones_sms: bool = False


class AdminUserCreate(AdminUserBase):
    password: str = Field(..., min_length=6, max_length=100)


class AdminUserUpdate(BaseModel):
    id_clinica: Optional[int] = Field(None, gt=0)
    tenant_id: Optional[str] = None
    id_rol: Optional[int] = Field(None, gt=0)
    nombres: Optional[str] = Field(None, min_length=2, max_length=100)
    apellidos: Optional[str] = Field(None, min_length=2, max_length=100)
    correo: Optional[EmailStr] = None
    telefono: Optional[str] = Field(None, max_length=30)
    foto_perfil: Optional[str] = Field(None, max_length=500)
    estado: Optional[str] = Field(None, min_length=1, max_length=20)
    notificaciones_push: Optional[bool] = None
    notificaciones_email: Optional[bool] = None
    notificaciones_sms: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=6, max_length=100)


class AdminUserStatusUpdate(BaseModel):
    activo: bool


class AdminUserResponse(BaseModel):
    id_usuario: int
    id_clinica: Optional[int] = None
    tenant_id: Optional[str] = None
    id_rol: Optional[int] = None
    nombre_rol: Optional[str] = None
    rol_nombre: Optional[str] = None
    nombres: str
    apellidos: str
    correo: str
    telefono: Optional[str] = None
    foto_perfil: Optional[str] = None
    estado: str
    notificaciones_push: bool
    notificaciones_email: bool
    notificaciones_sms: bool
    fecha_creacion: Optional[datetime] = None
    fecha_actualizacion: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
