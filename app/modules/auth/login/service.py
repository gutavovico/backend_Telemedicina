from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.core.security import hash_password, verify_password
from app.modules.auth.models import Usuario
from app.modules.auth.login.schemas import UsuarioCreate


def get_user_by_email(db: Session, correo: str) -> Optional[Usuario]:
    return db.query(Usuario).filter(Usuario.correo == correo.lower().strip()).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[Usuario]:
    return db.query(Usuario).filter(Usuario.id_usuario == user_id).first()


def authenticate_user(db: Session, correo: str, password: str) -> Optional[Usuario]:
    user = get_user_by_email(db, correo)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_user(db: Session, user_data: UsuarioCreate) -> Usuario:
    existing_user = get_user_by_email(db, user_data.correo)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario con este correo electrónico",
        )

    new_user = Usuario(
        id_clinica=user_data.id_clinica,
        id_rol=user_data.id_rol,
        nombres=user_data.nombres.strip(),
        apellidos=user_data.apellidos.strip(),
        correo=user_data.correo.lower().strip(),
        telefono=user_data.telefono.strip() if user_data.telefono else None,
        password_hash=hash_password(user_data.password),
        foto_perfil=user_data.foto_perfil.strip() if user_data.foto_perfil else None,
        estado="activo",
        notificaciones_push=user_data.notificaciones_push,
        notificaciones_email=user_data.notificaciones_email,
        notificaciones_sms=user_data.notificaciones_sms,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
