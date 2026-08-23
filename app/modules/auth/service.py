from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.modules.auth.models import Usuario
from app.modules.auth.schemas import UsuarioCreate
from app.core.security import hash_password, verify_password


def get_user_by_email(db: Session, correo: str) -> Optional[Usuario]:
    """Find a user by their email address."""
    return db.query(Usuario).filter(Usuario.correo == correo.lower()).first()


def get_user_by_id(db: Session, id_usuario: int) -> Optional[Usuario]:
    """Find a user by their ID."""
    return db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()


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
