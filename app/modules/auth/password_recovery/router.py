from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.password_recovery.schemas import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
)
from app.modules.auth.password_recovery.service import (
    FORGOT_PASSWORD_GENERIC,
    request_password_reset,
    reset_password,
)

router = APIRouter(tags=["Autenticación - Recuperación (CU23)"])


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Solicitar código de recuperación de contraseña",
    description="Genera un código HMAC-SHA256 de 6 dígitos con expiración de 30 min y respuesta genérica.",
)
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Solicita el envío de un código de recuperación al correo indicado."""
    debug_code = request_password_reset(db=db, correo=data.correo)
    response = ForgotPasswordResponse(detail=FORGOT_PASSWORD_GENERIC)
    if debug_code:
        response.debug_code = debug_code
    return response


@router.post(
    "/reset-password",
    summary="Restablecer contraseña con código de recuperación",
    description="Valida el código de 6 dígitos dentro de los 30 minutos y actualiza la contraseña.",
)
def reset_password_endpoint(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Restablece la contraseña validando el código de recuperación."""
    reset_password(
        db=db,
        correo=data.correo,
        codigo=data.codigo,
        nueva_password=data.nueva_password,
    )
    return {"detail": "Contraseña restablecida exitosamente."}
