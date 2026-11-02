"""RBAC del dominio backup: solo ADMIN de clínica.

El Super Administrador global solo gestiona clínicas y tiene denegado
el acceso a copias de seguridad (generar/listar/descargar/restaurar/config).
Rol canónico en seed: ``ADMIN`` (id_rol=1); se aceptan variantes
``ADMINISTRADOR``/``ADMINISTRACION`` por compatibilidad + ``id_rol == 1``.
"""

from fastapi import Depends, HTTPException, status

from app.modules.auth.dependencies import (
    ADMIN_ROLE_ID,
    _is_global_super_admin,
    get_current_user,
)
from app.modules.auth.models import Usuario

_ROLES_ADMIN = ("ADMIN", "ADMINISTRADOR", "ADMINISTRACION")


def _nombre_rol(user: Usuario) -> str:
    if isinstance(getattr(user, "rol", None), str) and user.rol:
        return user.rol.strip().upper()
    rol_rel = getattr(user, "rol_rel", None)
    nombre = getattr(rol_rel, "nombre", None) if rol_rel else None
    if isinstance(nombre, str) and nombre:
        return nombre.strip().upper()
    return ""


def require_backup_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Solo ADMIN de clínica con ``id_clinica`` (Super denegado)."""
    if _is_global_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El Super Administrador solo gestiona clínicas. Las copias de seguridad son del ADMIN de cada clínica.",
        )
    nombre = _nombre_rol(current_user)
    es_admin = current_user.id_rol == ADMIN_ROLE_ID or nombre in _ROLES_ADMIN
    if not es_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el ADMIN de la clínica puede gestionar copias de seguridad.",
        )
    if current_user.id_clinica is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta autenticada no está asociada a una clínica.",
        )
    return current_user


# Compatibilidad con imports previos: todo el dominio exige ADMIN de clínica.
require_backup_lector = require_backup_admin
require_backup_super = require_backup_admin


__all__ = ["require_backup_admin", "require_backup_lector", "require_backup_super"]
