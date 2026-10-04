from datetime import datetime
from typing import Literal, Optional
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
    # Rol y clinica: los guards por rol de Angular/Flutter dependen de `rol`.
    id_rol: Optional[int] = None
    id_clinica: Optional[int] = None
    rol: Optional[str] = None
    token_version: int = 0

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


class LogoutRequest(BaseModel):
    """Cierre global de sesion (CU24).

    Se envia el `refresh_token` en el body y no como Bearer porque, tras un
    cierre de sesion, el access token ya puede estar invalidado y el cliente
    aun debe poder cerrar la sesion de forma idempotente.
    """

    refresh_token: str = Field(..., examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."])


class ForgotPasswordRequest(BaseModel):
    correo: EmailStr = Field(..., examples=["juan.perez@ejemplo.com"])
    # Canal de entrega del código (CU23). "email" es el valor por defecto, de modo
    # que un cliente que no envíe el campo conserva el comportamiento anterior.
    canal: Literal["email", "sms"] = Field(
        default="email",
        description="Canal por el que se despacha el código de recuperación",
        examples=["sms"],
    )
    # Necesario solo para el canal SMS. Si falta, el teléfono registrado es el
    # que se usa; se acepta aquí para no depender de una segunda consulta.
    telefono: Optional[str] = Field(default=None, examples=["+59170000000"])


class ResetPasswordRequest(BaseModel):
    correo: EmailStr = Field(..., examples=["juan.perez@ejemplo.com"])
    codigo: str = Field(..., min_length=6, max_length=6, examples=["123456"])
    nueva_password: str = Field(..., min_length=6, max_length=100, examples=["NuevaPasswordSegura123"])


class ForgotPasswordResponse(BaseModel):
    detail: str
    # Solo presente en modo desarrollo (EMAIL_ENABLED=False) para facilitar la demo
    debug_code: Optional[str] = None


class SessionStatusResponse(BaseModel):
    """Estado de inactividad de la sesion actual (CU23).

    Lo consumen el aviso de 60 s y el cierre automatico de Angular y Flutter:
    el contador local es una aproximacion y el servidor es la fuente de verdad.
    """

    segundos_restantes: int
    ventana_segundos: int
    aviso_segundos: int
