from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.modules.auth.models import Clinica, Permiso, Rol, RolPermiso

ROL_ESTADO_ACTIVO = "ACTIVO"
ROL_ESTADO_INACTIVO = "INACTIVO"
PERMISO_ESTADO_ACTIVO = "ACTIVO"


def list_roles(db: Session) -> list[dict[str, Any]]:
    roles = db.query(Rol).options(joinedload(Rol.permisos)).order_by(Rol.id_rol.asc()).all()
    return [_serialize_role(role) for role in roles]


def get_role_or_404(db: Session, id_rol: int) -> Rol:
    role = (
        db.query(Rol)
        .options(joinedload(Rol.permisos))
        .filter(Rol.id_rol == id_rol)
        .first()
    )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado.",
        )
    return role


def get_role_detail(db: Session, id_rol: int) -> dict[str, Any]:
    return _serialize_role(get_role_or_404(db, id_rol))


def create_role(db: Session, role_data: dict[str, Any]) -> dict[str, Any]:
    normalized_name = role_data["nombre"].strip()
    normalized_state = _normalize_role_state(role_data.get("estado", ROL_ESTADO_ACTIVO))

    if role_data.get("id_clinica") is not None:
        _validate_clinica_exists(db, role_data["id_clinica"])

    _ensure_role_name_unique(db, normalized_name, role_data.get("id_clinica"))

    role = Rol(
        id_clinica=role_data.get("id_clinica"),
        nombre=normalized_name,
        descripcion=_strip_optional(role_data.get("descripcion")),
        estado=normalized_state,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return _serialize_role(role)


def update_role(db: Session, id_rol: int, role_data: dict[str, Any]) -> dict[str, Any]:
    role = get_role_or_404(db, id_rol)
    update_data = dict(role_data)

    target_clinica = update_data.get("id_clinica", role.id_clinica)
    if target_clinica is not None:
        _validate_clinica_exists(db, target_clinica)

    if "nombre" in update_data:
        normalized_name = update_data["nombre"].strip()
        _ensure_role_name_unique(db, normalized_name, target_clinica, exclude_role_id=role.id_rol)
        role.nombre = normalized_name

    if "descripcion" in update_data:
        role.descripcion = _strip_optional(update_data["descripcion"])
    if "id_clinica" in update_data:
        role.id_clinica = target_clinica
    if "estado" in update_data:
        role.estado = _normalize_role_state(update_data["estado"])

    db.add(role)
    db.commit()
    db.refresh(role)
    return _serialize_role(role)


def set_role_status(db: Session, id_rol: int, activo: bool) -> dict[str, Any]:
    role = get_role_or_404(db, id_rol)
    role.estado = ROL_ESTADO_ACTIVO if activo else ROL_ESTADO_INACTIVO
    db.add(role)
    db.commit()
    db.refresh(role)
    return _serialize_role(role)


def list_permissions(db: Session) -> list[dict[str, Any]]:
    permissions = db.query(Permiso).order_by(Permiso.id_permiso.asc()).all()
    return [_serialize_permission(permission) for permission in permissions]


def get_role_permissions(db: Session, id_rol: int) -> list[dict[str, Any]]:
    role = get_role_or_404(db, id_rol)
    permissions = sorted(role.permisos, key=lambda permission: permission.id_permiso)
    return [_serialize_permission(permission) for permission in permissions]


def replace_role_permissions(db: Session, id_rol: int, id_permisos: list[int]) -> list[dict[str, Any]]:
    role = get_role_or_404(db, id_rol)
    if role.estado != ROL_ESTADO_ACTIVO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pueden asignar permisos a un rol inactivo.",
        )

    unique_permission_ids = list(dict.fromkeys(id_permisos))
    permissions_by_id = {
        permission.id_permiso: permission
        for permission in db.query(Permiso).filter(Permiso.id_permiso.in_(unique_permission_ids)).all()
    } if unique_permission_ids else {}

    missing_ids = [permission_id for permission_id in unique_permission_ids if permission_id not in permissions_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Permiso no encontrado: {missing_ids[0]}",
        )

    inactive_permissions = [
        permission.id_permiso
        for permission in permissions_by_id.values()
        if permission.estado != PERMISO_ESTADO_ACTIVO
    ]
    if inactive_permissions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El permiso {inactive_permissions[0]} no está activo.",
        )

    current_relations = {
        relation.id_permiso: relation
        for relation in db.query(RolPermiso).filter(RolPermiso.id_rol == id_rol).all()
    }

    target_ids = set(unique_permission_ids)
    current_ids = set(current_relations.keys())

    for permission_id in current_ids - target_ids:
        db.delete(current_relations[permission_id])

    for permission_id in target_ids - current_ids:
        db.add(RolPermiso(id_rol=id_rol, id_permiso=permission_id))

    db.commit()
    return get_role_permissions(db, id_rol)


def _validate_clinica_exists(db: Session, id_clinica: int) -> None:
    clinica = db.query(Clinica).filter(Clinica.id_clinica == id_clinica).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clínica no encontrada.",
        )


def _ensure_role_name_unique(
    db: Session,
    nombre: str,
    id_clinica: int | None,
    exclude_role_id: int | None = None,
) -> None:
    query = db.query(Rol).filter(func.lower(Rol.nombre) == nombre.lower())
    if id_clinica is None:
        query = query.filter(Rol.id_clinica.is_(None))
    else:
        query = query.filter(Rol.id_clinica == id_clinica)
    if exclude_role_id is not None:
        query = query.filter(Rol.id_rol != exclude_role_id)

    existing_role = query.first()
    if existing_role:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un rol con ese nombre para la clínica indicada.",
        )


def _normalize_role_state(estado: str) -> str:
    normalized = estado.strip().upper()
    if normalized not in {ROL_ESTADO_ACTIVO, ROL_ESTADO_INACTIVO}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Estado de rol no válido.",
        )
    return normalized


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _serialize_role(role: Rol) -> dict[str, Any]:
    return {
        "id_rol": role.id_rol,
        "id_clinica": role.id_clinica,
        "nombre": role.nombre,
        "descripcion": role.descripcion,
        "estado": role.estado,
    }


def _serialize_permission(permission: Permiso) -> dict[str, Any]:
    return {
        "id_permiso": permission.id_permiso,
        "nombre": permission.nombre,
        "descripcion": permission.descripcion,
        "modulo": permission.modulo,
        "accion": permission.accion,
        "estado": permission.estado,
    }
