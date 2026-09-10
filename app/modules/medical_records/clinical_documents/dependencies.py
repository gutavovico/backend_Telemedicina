from typing import Optional
from fastapi import Depends, HTTPException, status
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario

# Permiso granular de lectura requerido por cada tipo de documento (matriz CU12)
DOCUMENT_READ_PERMISSION_BY_TYPE = {
    "RECETA": "documents:read:prescriptions",
    "ORDEN_LAB": "documents:read:lab_orders",
    "RESULTADO_LAB": "documents:read:lab_results",
    "CERTIFICADO": "documents:read:certificates",
    "INDICACION": "documents:read:certificates",
}

PERMISO_DOWNLOAD = "documents:download"
PERMISO_SEARCH = "documents:search"


def get_role_name(db: Session, id_rol: Optional[int]) -> Optional[str]:
    """Resuelve el nombre del rol mediante SQL crudo (evita dependencia del
    esquema ORM de roles, que difiere del esquema real en Neon)."""
    if id_rol is None:
        return None
    row = db.execute(
        sql_text("SELECT nombre FROM roles WHERE id_rol = :rid"),
        {"rid": id_rol},
    ).first()
    return row[0].upper() if row else None


def user_has_permission(db: Session, id_rol: Optional[int], permiso: str) -> bool:
    """Verifica si el rol del usuario posee el permiso granular (permisos + rol_permisos)."""
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


def require_document_permission(permiso: str):
    """Dependency factory: exige que el rol del usuario tenga el permiso dado."""
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


def require_roles_raw(allowed_roles):
    """Dependency factory por rol (vía SQL crudo).

    Evita la dependencia del ORM ``Rol`` (cuyo esquema difiere del real en
    Neon: la tabla roles no tiene la columna fecha_creacion esperada por el
    modelo). Consistente con ``require_roles`` de auth pero robusto a Neon.
    """
    def checker(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        role_name = get_role_name(db, current_user.id_rol)
        allowed_upper = [r.upper() for r in allowed_roles]
        # ADMIN_ROLE_ID = 1 (misma regla que auth.dependencies.require_roles)
        if current_user.id_rol == 1:
            return current_user
        if role_name not in allowed_upper:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso denegado. Se requiere uno de los siguientes roles: {', '.join(allowed_roles)}",
            )
        return current_user
    return checker


def user_can_read_document_type(db: Session, id_rol: Optional[int], tipo_documento: str) -> bool:
    """Verifica el permiso granular de lectura para un tipo de documento (matriz CU12)."""
    permiso = DOCUMENT_READ_PERMISSION_BY_TYPE.get(tipo_documento)
    if permiso is None:
        return False
    return user_has_permission(db, id_rol, permiso)