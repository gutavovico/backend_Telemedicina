from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.core.email import send_password_reset_email
from app.core.security import generate_reset_code, hash_password, verify_reset_code
from app.modules.auth.models import Usuario

FORGOT_PASSWORD_GENERIC = "Si el correo está registrado, recibirás un código de recuperación."


def request_password_reset(db: Session, correo: str) -> Optional[str]:
    """Genera el código de 6 dígitos para el usuario si existe y lo despacha por correo."""
    user = db.query(Usuario).filter(Usuario.correo == correo.lower().strip()).first()
    if not user or user.estado.lower() != "activo":
        return None
    codigo = generate_reset_code(user.id_usuario)
    debug_code = send_password_reset_email(user.correo, codigo)
    return debug_code


def reset_password(db: Session, correo: str, codigo: str, nueva_password: str) -> None:
    """Valida el código de 6 dígitos y actualiza la contraseña del usuario."""
    user = db.query(Usuario).filter(Usuario.correo == correo.lower().strip()).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código de recuperación inválido o expirado.",
        )

    valido = verify_reset_code(user.id_usuario, codigo)
    if not valido:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código de recuperación inválido o expirado.",
        )

    user.password_hash = hash_password(nueva_password)
    user.token_version += 1
    db.commit()
