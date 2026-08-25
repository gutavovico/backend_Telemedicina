from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.security import hash_password
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.auth.service import get_user_by_email, get_user_by_id
from app.modules.users.schemas import AdminUserCreate, AdminUserUpdate

USUARIO_ESTADO_ACTIVO = "activo"
USUARIO_ESTADO_INACTIVO = "inactivo"
ROL_ESTADO_ACTIVO = "ACTIVO"


def list_users(db: Session) -> list[dict[str, Any]]:
    users = (
        db.query(Usuario)
        .options(joinedload(Usuario.rol))
        .order_by(Usuario.id_usuario.asc())
        .all()
    )
    return [_serialize_user(user) for user in users]


def get_user_or_404(db: Session, id_usuario: int) -> Usuario:
    user = (
        db.query(Usuario)
        .options(joinedload(Usuario.rol))
        .filter(Usuario.id_usuario == id_usuario)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )
    return user


def get_user_detail(db: Session, id_usuario: int) -> dict[str, Any]:
    return _serialize_user(get_user_or_404(db, id_usuario))


def create_admin_user(db: Session, user_data: AdminUserCreate) -> dict[str, Any]:
    if get_user_by_email(db, user_data.correo):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario registrado con este correo electrónico.",
        )

    role = _get_active_role_or_error(db, user_data.id_rol)
    _validate_clinica_exists(db, user_data.id_clinica)
    _validate_role_clinic(role, user_data.id_clinica)

    new_user = Usuario(
        id_clinica=user_data.id_clinica,
        id_rol=user_data.id_rol,
        nombres=user_data.nombres.strip(),
        apellidos=user_data.apellidos.strip(),
        correo=user_data.correo.lower().strip(),
        telefono=_strip_optional(user_data.telefono),
        password_hash=hash_password(user_data.password),
        foto_perfil=_strip_optional(user_data.foto_perfil),
        estado=_normalize_estado(user_data.estado),
        notificaciones_push=user_data.notificaciones_push,
        notificaciones_email=user_data.notificaciones_email,
        notificaciones_sms=user_data.notificaciones_sms,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    db.refresh(new_user, attribute_names=["rol"])
    return _serialize_user(new_user)


def update_admin_user(db: Session, id_usuario: int, user_data: AdminUserUpdate) -> dict[str, Any]:
    user = get_user_or_404(db, id_usuario)

    update_data = user_data.model_dump(exclude_unset=True)
    target_clinica = update_data.get("id_clinica", user.id_clinica)
    target_rol_id = update_data.get("id_rol", user.id_rol)

    if target_clinica is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="id_clinica es obligatorio para el usuario.",
        )

    _validate_clinica_exists(db, target_clinica)

    if "correo" in update_data:
        correo = update_data["correo"].lower().strip()
        existing_user = get_user_by_email(db, correo)
        if existing_user and existing_user.id_usuario != user.id_usuario:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un usuario registrado con este correo electrónico.",
            )
        user.correo = correo

    if target_rol_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="id_rol es obligatorio para el usuario.",
        )

    role = _get_active_role_or_error(db, target_rol_id)
    _validate_role_clinic(role, target_clinica)

    user.id_clinica = target_clinica
    user.id_rol = target_rol_id

    if "nombres" in update_data:
        user.nombres = update_data["nombres"].strip()
    if "apellidos" in update_data:
        user.apellidos = update_data["apellidos"].strip()
    if "telefono" in update_data:
        user.telefono = _strip_optional(update_data["telefono"])
    if "foto_perfil" in update_data:
        user.foto_perfil = _strip_optional(update_data["foto_perfil"])
    if "estado" in update_data:
        user.estado = _normalize_estado(update_data["estado"])
    if "notificaciones_push" in update_data:
        user.notificaciones_push = update_data["notificaciones_push"]
    if "notificaciones_email" in update_data:
        user.notificaciones_email = update_data["notificaciones_email"]
    if "notificaciones_sms" in update_data:
        user.notificaciones_sms = update_data["notificaciones_sms"]
    if "password" in update_data:
        user.password_hash = hash_password(update_data["password"])

    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(user, attribute_names=["rol"])
    return _serialize_user(user)


def set_user_status(db: Session, id_usuario: int, activo: bool) -> dict[str, Any]:
    user = get_user_or_404(db, id_usuario)
    user.estado = USUARIO_ESTADO_ACTIVO if activo else USUARIO_ESTADO_INACTIVO
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(user, attribute_names=["rol"])
    return _serialize_user(user)


def _get_active_role_or_error(db: Session, id_rol: int) -> Rol:
    role = db.query(Rol).filter(Rol.id_rol == id_rol).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado.",
        )
    if role.estado != ROL_ESTADO_ACTIVO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol indicado no está activo.",
        )
    return role


def _validate_clinica_exists(db: Session, id_clinica: int) -> None:
    clinica = db.query(Clinica).filter(Clinica.id_clinica == id_clinica).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clínica no encontrada.",
        )


def _validate_role_clinic(role: Rol, id_clinica: int) -> None:
    if role.id_clinica is not None and role.id_clinica != id_clinica:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol no corresponde a la clínica indicada.",
        )


def _normalize_estado(estado: str) -> str:
    normalized = estado.strip().lower()
    if normalized not in {USUARIO_ESTADO_ACTIVO, USUARIO_ESTADO_INACTIVO}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Estado de usuario no válido.",
        )
    return normalized


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _serialize_user(user: Usuario) -> dict[str, Any]:
    return {
        "id_usuario": user.id_usuario,
        "id_clinica": user.id_clinica,
        "id_rol": user.id_rol,
        "nombre_rol": user.rol.nombre if user.rol else None,
        "nombres": user.nombres,
        "apellidos": user.apellidos,
        "correo": user.correo,
        "telefono": user.telefono,
        "foto_perfil": user.foto_perfil,
        "estado": user.estado,
        "notificaciones_push": user.notificaciones_push,
        "notificaciones_email": user.notificaciones_email,
        "notificaciones_sms": user.notificaciones_sms,
        "fecha_creacion": user.fecha_creacion,
        "fecha_actualizacion": user.fecha_actualizacion,
    }
