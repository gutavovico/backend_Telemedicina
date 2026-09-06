from typing import Any, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.core.security import hash_password
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.auth.users_management.schemas import AdminUserCreate, AdminUserUpdate

USUARIO_ESTADO_ACTIVO = "activo"
USUARIO_ESTADO_INACTIVO = "inactivo"
ROL_ESTADO_ACTIVO = "ACTIVO"


def _serialize_user(user: Usuario) -> dict[str, Any]:
    role_name = user.rol.nombre if user.rol else None
    return {
        "id_usuario": user.id_usuario,
        "id_clinica": user.id_clinica,
        "tenant_id": str(user.id_clinica) if user.id_clinica else None,
        "id_rol": user.id_rol,
        "nombre_rol": role_name,
        "rol_nombre": role_name,
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
        "created_at": user.fecha_creacion,
    }


def list_users(db: Session, tenant_id: Optional[int] = None) -> list[dict[str, Any]]:
    query = db.query(Usuario).options(joinedload(Usuario.rol))
    if tenant_id is not None:
        query = query.filter(Usuario.id_clinica == tenant_id)
    users = query.order_by(Usuario.id_usuario.asc()).all()
    return [_serialize_user(user) for user in users]


def get_user_or_404(db: Session, id_usuario: int, tenant_id: Optional[int] = None) -> Usuario:
    query = db.query(Usuario).options(joinedload(Usuario.rol)).filter(Usuario.id_usuario == id_usuario)
    if tenant_id is not None:
        query = query.filter(Usuario.id_clinica == tenant_id)
    user = query.first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )
    return user


def get_user_detail(db: Session, id_usuario: int, tenant_id: Optional[int] = None) -> dict[str, Any]:
    return _serialize_user(get_user_or_404(db, id_usuario, tenant_id))


def create_admin_user(db: Session, user_data: AdminUserCreate, current_tenant_id: Optional[int] = None) -> dict[str, Any]:
    target_clinica = current_tenant_id if current_tenant_id is not None else user_data.id_clinica

    # Validación de duplicidad con scope de tenant
    query_existing = db.query(Usuario).filter(Usuario.correo == user_data.correo.lower().strip())
    if target_clinica is not None:
        query_existing = query_existing.filter(Usuario.id_clinica == target_clinica)
    if query_existing.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario registrado con este correo electrónico en la clínica.",
        )

    role = _get_active_role_or_error(db, user_data.id_rol)
    if target_clinica is not None:
        _validate_clinica_exists(db, target_clinica)
        _validate_role_clinic(role, target_clinica)

    new_user = Usuario(
        id_clinica=target_clinica,
        id_rol=user_data.id_rol,
        nombres=user_data.nombres.strip(),
        apellidos=user_data.apellidos.strip(),
        correo=user_data.correo.lower().strip(),
        telefono=user_data.telefono.strip() if user_data.telefono else None,
        password_hash=hash_password(user_data.password),
        foto_perfil=user_data.foto_perfil.strip() if user_data.foto_perfil else None,
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


def update_admin_user(db: Session, id_usuario: int, user_data: AdminUserUpdate, current_tenant_id: Optional[int] = None) -> dict[str, Any]:
    user = get_user_or_404(db, id_usuario, current_tenant_id)
    update_data = user_data.model_dump(exclude_unset=True)

    target_clinica = current_tenant_id if current_tenant_id is not None else update_data.get("id_clinica", user.id_clinica)
    target_rol_id = update_data.get("id_rol", user.id_rol)

    if target_clinica is not None:
        _validate_clinica_exists(db, target_clinica)

    if "correo" in update_data:
        correo = update_data["correo"].lower().strip()
        query_dup = db.query(Usuario).filter(Usuario.correo == correo, Usuario.id_usuario != user.id_usuario)
        if target_clinica is not None:
            query_dup = query_dup.filter(Usuario.id_clinica == target_clinica)
        if query_dup.first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un usuario registrado con este correo electrónico en la clínica.",
            )
        user.correo = correo

    if target_rol_id is not None:
        role = _get_active_role_or_error(db, target_rol_id)
        if target_clinica is not None:
            _validate_role_clinic(role, target_clinica)
        user.id_rol = target_rol_id

    user.id_clinica = target_clinica

    if "nombres" in update_data:
        user.nombres = update_data["nombres"].strip()
    if "apellidos" in update_data:
        user.apellidos = update_data["apellidos"].strip()
    if "telefono" in update_data:
        user.telefono = update_data["telefono"].strip() if update_data["telefono"] else None
    if "foto_perfil" in update_data:
        user.foto_perfil = update_data["foto_perfil"].strip() if update_data["foto_perfil"] else None
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


def set_user_status(db: Session, id_usuario: int, activo: bool, current_tenant_id: Optional[int] = None) -> dict[str, Any]:
    user = get_user_or_404(db, id_usuario, current_tenant_id)
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
