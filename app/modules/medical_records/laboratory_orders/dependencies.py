from typing import Optional
from fastapi import Depends, HTTPException, status
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario

PERMISO_CREATE = "lab_orders:create"
PERMISO_READ = "lab_orders:read"
PERMISO_DOWNLOAD = "lab_orders:download"


def get_role_name(db: Session, id_rol: Optional[int]) -> Optional[str]:
    if id_rol is None:
        return None
    row = db.execute(
        sql_text("SELECT nombre FROM roles WHERE id_rol = :rid"),
        {"rid": id_rol},
    ).first()
    return row[0].upper() if row else None


def user_has_permission(db: Session, id_rol: Optional[int], permiso: str) -> bool:
    if id_rol is None:
        return False
    row = db.execute(
        sql_text(
            "SELECT 1 FROM rol_permisos rp "
            "JOIN permisos p ON p.id_permiso = rp.id_permiso "
            "WHERE rp.id_rol = :rid AND p.nombre = :perm AND p.estado = 'ACTIVO'"
        ),
        {"rid": id_rol, "perm": permiso},
    ).first()
    return row is not None


def require_lab_order_permission(permiso: str):
    def checker(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        if not user_has_permission(db, current_user.id_rol, permiso):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso denegado. Se requiere el permiso '{permiso}'.",
            )
        return current_user
    return checker


def require_roles_lab_order(allowed_roles):
    def checker(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        role_name = get_role_name(db, current_user.id_rol)
        allowed_upper = [r.upper() for r in allowed_roles]
        if current_user.id_rol == 1:
            return current_user
        if role_name not in allowed_upper:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso denegado. Se requiere uno de los siguientes roles: {', '.join(allowed_roles)}",
            )
        return current_user
    return checker


def user_can_access_lab_order(db: Session, current_user: Usuario, orden) -> bool:
    """Verifica si el usuario puede acceder a una orden específica."""
    role_name = get_role_name(db, current_user.id_rol) or ""
    if role_name == "MEDICO":
        return orden.id_medico == current_user.id_usuario
    return role_name in ("ADMIN", "RECEPCION")