from typing import Any, List, Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from app.modules.auth.models import Clinica, Permiso, Rol, RolPermiso

ROL_ESTADO_ACTIVO = "ACTIVO"
ROL_ESTADO_INACTIVO = "INACTIVO"
PERMISO_ESTADO_ACTIVO = "ACTIVO"


def _serialize_role(role: Rol) -> dict[str, Any]:
    return {
        "id_rol": role.id_rol,
        "id_clinica": role.id_clinica,
        "tenant_id": str(role.id_clinica) if role.id_clinica else None,
        "nombre": role.nombre,
        "descripcion": role.descripcion,
        "estado": role.estado,
    }


def _serialize_permission(permission: Permiso) -> dict[str, Any]:
    return {
        "id_permiso": permission.id_permiso,
        "codigo": f"{permission.modulo.upper()}_{permission.accion.upper()}",
        "nombre": permission.nombre,
        "descripcion": permission.descripcion,
        "modulo": permission.modulo,
        "accion": permission.accion,
        "estado": permission.estado,
    }


def list_roles(db: Session, tenant_id: Optional[int] = None) -> list[dict[str, Any]]:
    query = db.query(Rol).options(joinedload(Rol.permisos))
    if tenant_id is not None:
        query = query.filter((Rol.id_clinica == tenant_id) | (Rol.id_clinica.is_(None)))
    roles = query.order_by(Rol.id_rol.asc()).all()
    return [_serialize_role(role) for role in roles]


def get_role_or_404(db: Session, id_rol: int, tenant_id: Optional[int] = None) -> Rol:
    query = db.query(Rol).options(joinedload(Rol.permisos)).filter(Rol.id_rol == id_rol)
    if tenant_id is not None:
        query = query.filter((Rol.id_clinica == tenant_id) | (Rol.id_clinica.is_(None)))
    role = query.first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado.",
        )
    return role


def get_role_detail(db: Session, id_rol: int, tenant_id: Optional[int] = None) -> dict[str, Any]:
    return _serialize_role(get_role_or_404(db, id_rol, tenant_id))


def create_role(db: Session, role_data: dict[str, Any], current_tenant_id: Optional[int] = None) -> dict[str, Any]:
    if current_tenant_id is not None:
        if role_data.get("id_clinica") is not None and role_data.get("id_clinica") != current_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se permite especificar un id_clinica diferente al del contexto del tenant",
            )
        target_clinica = current_tenant_id
    else:
        target_clinica = role_data.get("id_clinica")

    normalized_name = role_data["nombre"].strip()
    normalized_state = _normalize_role_state(role_data.get("estado", ROL_ESTADO_ACTIVO))

    if target_clinica is not None:
        _validate_clinica_exists(db, target_clinica)

    _ensure_role_name_unique(db, normalized_name, target_clinica)

    role = Rol(
        id_clinica=target_clinica,
        nombre=normalized_name,
        descripcion=role_data.get("descripcion", "").strip() or None if role_data.get("descripcion") else None,
        estado=normalized_state,
    )
    db.add(role)
    db.commit()
    db.refresh(role)

    try:
        from app.modules.auditoria.service import registrar_evento
        registrar_evento(
            db=db,
            id_usuario=1,
            id_clinica=role.id_clinica,
            tabla_afectada="roles",
            registro_id=role.id_rol,
            accion="INSERT",
            descripcion=f"Creación del rol: {role.nombre}",
            datos_nuevos={"nombre": role.nombre, "descripcion": role.descripcion, "estado": role.estado}
        )
    except Exception as e:
        print(f"Error auditoria rol create: {e}")

    return _serialize_role(role)


def update_role(db: Session, id_rol: int, role_data: dict[str, Any], current_tenant_id: Optional[int] = None) -> dict[str, Any]:
    role = get_role_or_404(db, id_rol, current_tenant_id)
    update_data = dict(role_data)

    datos_ant = {
        "nombre": role.nombre,
        "descripcion": role.descripcion,
        "estado": role.estado
    }

    target_clinica = current_tenant_id if current_tenant_id is not None else update_data.get("id_clinica", role.id_clinica)
    if target_clinica is not None:
        _validate_clinica_exists(db, target_clinica)

    if "nombre" in update_data:
        normalized_name = update_data["nombre"].strip()
        _ensure_role_name_unique(db, normalized_name, target_clinica, exclude_role_id=role.id_rol)
        role.nombre = normalized_name

    if "descripcion" in update_data:
        role.descripcion = update_data["descripcion"].strip() or None if update_data.get("descripcion") else None
    if "id_clinica" in update_data and current_tenant_id is None:
        role.id_clinica = target_clinica
    if "estado" in update_data:
        role.estado = _normalize_role_state(update_data["estado"])

    db.add(role)
    db.commit()
    db.refresh(role)

    datos_nue = {
        "nombre": role.nombre,
        "descripcion": role.descripcion,
        "estado": role.estado
    }

    try:
        from app.modules.auditoria.service import registrar_evento
        registrar_evento(
            db=db,
            id_usuario=1,
            id_clinica=role.id_clinica,
            tabla_afectada="roles",
            registro_id=role.id_rol,
            accion="UPDATE",
            descripcion=f"Actualización del rol #{role.id_rol}: {role.nombre}",
            datos_anteriores=datos_ant,
            datos_nuevos=datos_nue
        )
    except Exception as e:
        print(f"Error auditoria rol update: {e}")

    return _serialize_role(role)


def set_role_status(db: Session, id_rol: int, activo: bool, current_tenant_id: Optional[int] = None) -> dict[str, Any]:
    role = get_role_or_404(db, id_rol, current_tenant_id)
    estado_ant = role.estado
    role.estado = ROL_ESTADO_ACTIVO if activo else ROL_ESTADO_INACTIVO
    db.add(role)
    db.commit()
    db.refresh(role)

    try:
        from app.modules.auditoria.service import registrar_evento
        registrar_evento(
            db=db,
            id_usuario=1,
            id_clinica=role.id_clinica,
            tabla_afectada="roles",
            registro_id=role.id_rol,
            accion="UPDATE",
            descripcion=f"Cambio de estado del rol #{role.id_rol} a {role.estado}",
            datos_anteriores={"estado": estado_ant},
            datos_nuevos={"estado": role.estado}
        )
    except Exception as e:
        print(f"Error auditoria rol status: {e}")

    return _serialize_role(role)


def list_permissions(db: Session) -> list[dict[str, Any]]:
    permissions = db.query(Permiso).order_by(Permiso.id_permiso.asc()).all()
    return [_serialize_permission(permission) for permission in permissions]


def get_role_permissions(db: Session, id_rol: int, current_tenant_id: Optional[int] = None) -> list[dict[str, Any]]:
    role = get_role_or_404(db, id_rol, current_tenant_id)
    permissions = sorted(role.permisos, key=lambda permission: permission.id_permiso)
    return [_serialize_permission(permission) for permission in permissions]


def replace_role_permissions(db: Session, id_rol: int, id_permisos: List[int], current_tenant_id: Optional[int] = None) -> list[dict[str, Any]]:
    role = get_role_or_404(db, id_rol, current_tenant_id)
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

    missing_ids = [pid for pid in unique_permission_ids if pid not in permissions_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Permiso no encontrado: {missing_ids[0]}",
        )

    inactive_permissions = [
        pid for pid, perm in permissions_by_id.items() if perm.estado != PERMISO_ESTADO_ACTIVO
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

    for pid in current_ids - target_ids:
        db.delete(current_relations[pid])

    for pid in target_ids - current_ids:
        db.add(RolPermiso(id_rol=id_rol, id_permiso=pid))

    db.commit()

    try:
        from app.modules.auditoria.service import registrar_evento
        registrar_evento(
            db=db,
            id_usuario=1,
            id_clinica=role.id_clinica,
            tabla_afectada="rol_permisos",
            registro_id=role.id_rol,
            accion="UPDATE",
            descripcion=f"Actualización de permisos asignados al rol #{role.id_rol} ({role.nombre})",
            datos_anteriores={"permisos": list(current_ids)},
            datos_nuevos={"permisos": list(target_ids)}
        )
    except Exception as e:
        print(f"Error auditoria rol permisos: {e}")

    return get_role_permissions(db, id_rol, current_tenant_id)


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
    id_clinica: Optional[int],
    exclude_role_id: Optional[int] = None,
) -> None:
    query = db.query(Rol).filter(func.lower(Rol.nombre) == nombre.lower())
    if id_clinica is None:
        query = query.filter(Rol.id_clinica.is_(None))
    else:
        query = query.filter((Rol.id_clinica == id_clinica) | (Rol.id_clinica.is_(None)))
    if exclude_role_id is not None:
        query = query.filter(Rol.id_rol != exclude_role_id)

    if query.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un rol con ese nombre para la clínica indicada o a nivel global.",
        )


def _normalize_role_state(estado: str) -> str:
    normalized = estado.strip().upper()
    if normalized not in {ROL_ESTADO_ACTIVO, ROL_ESTADO_INACTIVO}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Estado de rol no válido.",
        )
    return normalized
