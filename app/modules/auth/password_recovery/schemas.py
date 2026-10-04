from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class ForgotPasswordRequest(BaseModel):
    correo: EmailStr


class ForgotPasswordResponse(BaseModel):
    detail: str
    debug_code: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    correo: EmailStr
    codigo: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$", description="Código numérico de 6 dígitos")
    nueva_password: str = Field(..., min_length=8, max_length=100, description="Nueva contraseña segura")
