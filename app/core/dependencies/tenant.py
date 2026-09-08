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


def is_super_admin(user: Usuario) -> bool:
    """Checks if a user is a platform Super Administrator."""
    if user is None:
        return False
    try:
        rol = getattr(user, "rol", None)
        if rol:
            rol_name = rol.nombre.strip().upper()
            if (
                "SUPER" in rol_name
                or rol_name in {"SUPER ADMINISTRADOR", "SUPER_ADMINISTRADOR", "SUPER_ADMIN", "SUPERADMIN"}
            ):
                return True
    except Exception:
        pass

    if user.id_clinica is None:
        if user.id_rol == 1:
            return True
        try:
            rol = getattr(user, "rol", None)
            if rol:
                rol_name = rol.nombre.strip().upper()
                if (
                    rol_name in ADMIN_ROLE_NAMES
                    or rol_name.replace(" ", "_") in ADMIN_ROLE_NAMES
                    or "ADMIN" in rol_name
                ):
                    return True
        except Exception:
            pass
    return False


def require_super_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Dependency that enforces caller is a Super Administrator."""
    if not is_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: se requieren permisos de Super Administrador",
        )
    return current_user


def get_current_tenant(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Clinica:
    """
    Dependency that resolves and validates the active Clinica (Tenant).
    - For Super Admin: resolves tenant from X-Tenant-ID header (required when calling tenant endpoints).
    - For Tenant users: resolves strictly from current_user.id_clinica (X-Tenant-ID is ignored).
    - Validates that the clinic exists (404) and is in ACTIVO state (403).
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

    clinica = db.query(Clinica).filter(Clinica.id_clinica == tenant_id).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clínica no encontrada",
        )

    if clinica.estado.upper() != "ACTIVO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La clínica no está activa",
        )

    return clinica


def get_current_tenant_optional(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[Clinica]:
    """
    Optional tenant dependency.
    Returns Clinica if resolved and valid, or None if user is Super Admin without X-Tenant-ID.
    """
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

    clinica = db.query(Clinica).filter(Clinica.id_clinica == tenant_id).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clínica no encontrada",
        )

    if clinica.estado.upper() != "ACTIVO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La clínica no está activa",
        )

    return clinica
