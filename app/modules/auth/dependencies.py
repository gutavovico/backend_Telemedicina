from typing import List, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.auth.models import Usuario
from app.modules.auth.service import get_user_by_id
from app.modules.auth.session_service import enforce_inactivity

security = HTTPBearer(auto_error=False)
ADMIN_ROLE_ID = 1


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Usuario:
    """Dependency to retrieve the authenticated user from the Bearer JWT token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido: falta identificador de usuario",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido: identificador no numérico",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    # CU24: el cierre de sesion incrementa `token_version`, lo que invalida todos
    # los access tokens emitidos hasta entonces.
    token_version = payload.get("token_version")
    if token_version is not None and int(token_version) != int(user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión cerrada o token revocado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # CU23: ventana de inactividad por sesion.
    enforce_inactivity(
        db,
        payload.get("jti"),
        user_id,
        id_clinica=user.id_clinica,
    )

    if user.estado.lower() != "activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario está inactiva o suspendida",
        )

    return user


def get_current_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Optional[Usuario] = Depends(get_current_user),
) -> Optional[int]:
    """Resolves tenant_id from authenticated user or X-Tenant-ID header."""
    if current_user and current_user.id_clinica is not None:
        return current_user.id_clinica
    if x_tenant_id:
        try:
            return int(x_tenant_id)
        except ValueError:
            return None
    return None


def get_required_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Usuario = Depends(get_current_user),
) -> int:
    """Obtiene el tenant de una sesión asociada a una clínica."""
    if current_user.id_clinica is not None:
        return current_user.id_clinica
    if x_tenant_id:
        try:
            header_tenant = int(x_tenant_id)
        except ValueError:
            header_tenant = None
        if header_tenant is not None and _is_global_super_admin(current_user):
            return header_tenant
    if current_user.id_rol == 4:
        return 1
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="La cuenta autenticada no está asociada a una clínica",
    )


def _is_global_super_admin(current_user: Optional[Usuario]) -> bool:
    """Superadmin real: sin clínica Y con rol global (rol.id_clinica=None)."""
    if current_user is None or current_user.id_clinica is not None:
        return False
    rol_obj = getattr(current_user, "rol_rel", None)
    if rol_obj is not None and getattr(rol_obj, "id_clinica", None) is not None:
        return False
    if current_user.id_rol == 1:
        return True
    try:
        if isinstance(current_user.rol, str):
            rol_name = current_user.rol.strip().upper()
        elif rol_obj and getattr(rol_obj, "nombre", None):
            rol_name = rol_obj.nombre.strip().upper()
        else:
            rol_name = ""
        if "SUPER" in rol_name:
            return True
    except Exception:
        pass
    return False


def require_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Allow access only to users with the Administracion role (o Super Admin global)."""
    if _is_global_super_admin(current_user):
        return current_user
    if current_user.id_rol != ADMIN_ROLE_ID:
        if isinstance(current_user.rol, str):
            rol_name = current_user.rol.strip().upper()
        elif getattr(current_user, "rol_rel", None) and getattr(current_user.rol_rel, "nombre", None):
            rol_name = current_user.rol_rel.nombre.strip().upper()
        else:
            rol_name = ""
        if rol_name not in ["ADMIN", "ADMINISTRADOR", "ADMINISTRACION"] and "SUPER" not in rol_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos administrativos.",
            )
    return current_user


def require_roles(allowed_roles: List[str]):
    """Allow access to users matching any of the specified roles (o Super Admin global)."""
    def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        if _is_global_super_admin(current_user):
            return current_user

        if isinstance(current_user.rol, str):
            role_name = current_user.rol.strip().upper()
        elif getattr(current_user, "rol_rel", None) and getattr(current_user.rol_rel, "nombre", None):
            role_name = current_user.rol_rel.nombre.strip().upper()
        else:
            role_name = ""

        allowed_upper = [r.upper() for r in allowed_roles]

        if "ADMIN" in allowed_upper and current_user.id_rol == ADMIN_ROLE_ID:
            return current_user

        if role_name not in allowed_upper:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso denegado. Se requiere uno de los siguientes roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker

