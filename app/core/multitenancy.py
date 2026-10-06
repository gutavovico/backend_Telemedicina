"""Resolución central de tenant (multitenancy).

Ubicación exigida por openspec/project.md §4:
    app/core/multitenancy.py  # Dependencia get_current_tenant y validaciones

Estrategia: Shared Database + Shared Schema con discriminador
``id_clinica`` (FK a ``clinicas``). Ver project.md §2.1.
Desviación documentada del spec: el spec menciona ``tenant_id: UUID``,
el código histórico usa ``id_clinica: BIGINT``. Se mantiene BIGINT
para no romper migraciones/datos existentes.

Port adaptado de Sprint 1 (app/core/dependencies/tenant.py).
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Usuario

ADMIN_ROLE_NAMES = {
    "ADMIN",
    "ADMINISTRADOR",
    "ADMINISTRACION",
    "SUPER_ADMIN",
    "SUPERADMIN",
    "SUPER ADMINISTRADOR",
    "SUPER_ADMINISTRADOR",
}


def _rol_nombre(user: Usuario) -> str:
    """Nombre del rol soportando `Usuario.rol` str (property) u objeto con `.nombre`."""
    try:
        r = getattr(user, "rol", None)
        if isinstance(r, str) and r.strip():
            return r.strip().upper()
        if r is not None:
            n = getattr(r, "nombre", None)
            if n:
                return str(n).strip().upper()
        rel = getattr(user, "rol_rel", None)
        if rel is not None:
            n = getattr(rel, "nombre", None)
            if n:
                return str(n).strip().upper()
    except Exception:
        pass
    return ""


def _rol_id_clinica(user: Usuario):
    """`id_clinica` del rol (None = global). Se lee del objeto, nunca del str."""
    try:
        for obj in (getattr(user, "rol_rel", None), getattr(user, "rol", None)):
            if obj is not None and not isinstance(obj, str):
                return getattr(obj, "id_clinica", None)
    except Exception:
        pass
    return None


def is_super_admin(user: Usuario) -> bool:
    """Indica si el usuario es Super Administrador de plataforma.

    Endurecido vs Sprint 1: un rol de tenant (``rol.id_clinica is not None``)
    nunca otorga privilegio global, aunque ``user.id_clinica`` sea NULL
    (admin desvinculado). Solo un rol global (``rol.id_clinica is None``)
    + usuario sin clínica otorga superadmin.
    """
    if user is None:
        return False
    rol_name = _rol_nombre(user)
    rol_clinica = _rol_id_clinica(user)
    # Rol SUPER global (seed: "Super Administrador", id_clinica=None) + sin clínica.
    if "SUPER" in rol_name or rol_name in {
        "SUPER ADMINISTRADOR",
        "SUPER_ADMINISTRADOR",
        "SUPER_ADMIN",
        "SUPERADMIN",
    }:
        # Incluso el rol SUPER debe ser global, no de un tenant.
        if rol_clinica is None and user.id_clinica is None:
            return True
        return False

    if user.id_clinica is None:
        if user.id_rol == 1:
            # Si el rol 1 pertenece a un tenant, no es global.
            if rol_clinica is not None:
                return False
            return True
        if rol_clinica is not None:
            return False
        if (
            rol_name in ADMIN_ROLE_NAMES
            or rol_name.replace(" ", "_") in ADMIN_ROLE_NAMES
            or "ADMIN" in rol_name
        ):
            return True
    return False


def require_super_admin(
    current_user: Usuario = Depends(get_current_user),
) -> Usuario:
    """Dependencia que exige Super Administrador."""
    if not is_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: se requieren permisos de Super Administrador",
        )
    return current_user


def _get_clinica_or_raise(db: Session, tenant_id: int) -> Clinica:
    clinica = db.query(Clinica).filter(Clinica.id_clinica == tenant_id).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clínica no encontrada",
        )
    estado = (clinica.estado or "").upper()
    if estado != "ACTIVO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La clínica no está activa",
        )
    return clinica


def get_current_tenant(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Clinica:
    """Resuelve y valida el tenant activo.

    - Super Admin: resuelve desde header ``X-Tenant-ID`` (obligatorio).
    - Usuario de tenant: resuelve desde ``current_user.id_clinica`` (header ignorado).
    - Valida existencia (404) y estado ACTIVO (403).
    """
    if is_super_admin(current_user):
        if not x_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Super Administrador requiere el encabezado X-Tenant-ID para este recurso",
            )
        try:
            tenant_id = int(x_tenant_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Encabezado X-Tenant-ID inválido",
            )
    else:
        if current_user.id_clinica is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario no tiene una clínica asociada",
            )
        tenant_id = current_user.id_clinica

    return _get_clinica_or_raise(db, tenant_id)


def get_current_tenant_optional(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[Clinica]:
    """Variante opcional: retorna None para Super Admin sin header (vista global)."""
    if is_super_admin(current_user):
        if not x_tenant_id:
            return None
        try:
            tenant_id = int(x_tenant_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Encabezado X-Tenant-ID inválido",
            )
    else:
        if current_user.id_clinica is None:
            return None
        tenant_id = current_user.id_clinica

    return _get_clinica_or_raise(db, tenant_id)


def get_current_tenant_id_from_clinica(
    tenant: Optional[Clinica],
    current_user: Usuario,
) -> Optional[int]:
    """Helper para servicios que aún trabajan con int: Clinica -> id_clinica."""
    if tenant is not None:
        return tenant.id_clinica
    if is_super_admin(current_user):
        return None
    return current_user.id_clinica
