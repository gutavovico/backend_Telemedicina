from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.modules.auth.models import Usuario
from app.modules.auth.schemas import UsuarioCreate
from app.core.security import hash_password, verify_password
from app.core.security import generate_reset_code, verify_reset_code
from app.core.email import send_password_reset_email


FORGOT_PASSWORD_GENERIC = (
    "Si el correo está registrado, recibirás un código de recuperación."
)


def get_user_by_email(db: Session, correo: str) -> Optional[Usuario]:
    """Find a user by their email address."""
    return db.query(Usuario).filter(Usuario.correo == correo.lower()).first()


def get_user_by_id(db: Session, id_usuario: int) -> Optional[Usuario]:
    """Find a user by their ID."""
    return db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()


def request_password_reset(db: Session, correo: str) -> Optional[str]:
    """Genera y envía el código de recuperación de contraseña (CU23).

    Devuelve la respuesta genérica siempre (no filtra correos registrados).
    Retorna debug_code solo en modo desarrollo para facilitar la demo.
    """
    user = get_user_by_email(db, correo)
    if not user or user.estado != "activo":
        # Respuesta genérica para no revelar correos existentes
        return None

    codigo = generate_reset_code(user.id_usuario)
    debug_code = send_password_reset_email(user.correo, codigo)
    return debug_code


def reset_password(db: Session, correo: str, codigo: str, nueva_password: str) -> None:
    """Valida el código y actualiza la contraseña del usuario (CU23)."""
    user = get_user_by_email(db, correo)
    if not user or user.estado != "activo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo restablecer la contraseña. Verifica los datos.",
        )

    if not verify_reset_code(user.id_usuario, codigo):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código de recuperación inválido o expirado.",
        )

    user.password_hash = hash_password(nueva_password)
    db.add(user)
    db.commit()
    db.refresh(user)


def create_user(db: Session, user_data: UsuarioCreate) -> Usuario:
    """Create a new user with hashed password."""
    # Check if user already exists
    existing_user = get_user_by_email(db, user_data.correo)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario registrado con este correo electrónico."
        )

    # Hash the password
    hashed_pwd = hash_password(user_data.password)

    # Instantiate model
    new_user = Usuario(
        id_clinica=user_data.id_clinica,
        id_rol=user_data.id_rol,
        nombres=user_data.nombres.strip(),
        apellidos=user_data.apellidos.strip(),
        correo=user_data.correo.lower().strip(),
        telefono=user_data.telefono.strip() if user_data.telefono else None,
        password_hash=hashed_pwd,
        foto_perfil=user_data.foto_perfil.strip() if user_data.foto_perfil else None,
        estado="activo",
        notificaciones_push=user_data.notificaciones_push if user_data.notificaciones_push is not None else True,
        notificaciones_email=user_data.notificaciones_email if user_data.notificaciones_email is not None else True,
        notificaciones_sms=user_data.notificaciones_sms if user_data.notificaciones_sms is not None else False,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


def authenticate_user(db: Session, correo: str, password: str) -> Optional[Usuario]:
    """Authenticate user with email and password."""
    user = get_user_by_email(db, correo)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if user.estado != "activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario está inactiva o suspendida."
        )
    return user
