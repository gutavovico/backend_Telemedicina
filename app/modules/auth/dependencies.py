from typing import List, Optional
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.auth.models import Usuario

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
    
    user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    if payload.get("token_version", 0) != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión cerrada o token revocado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if user.estado.lower() != "activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario está inactiva o suspendida",
        )
    
    return user


def get_current_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Optional[Usuario] = Depends(get_current_user)
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
    """Obtiene el tenant de una sesión asociada a una clínica.

    Prioriza id_clinica del usuario autenticado. El header X-Tenant-ID
    NUNCA concede un tenant a un usuario sin clínica, salvo superadmin
    global verificado (rol global id_clinica=None). Esto evita la
    escalación donde un admin de tenant desvinculado (rol.id_clinica=1,
    user.id_clinica=None) se hacía pasar por superadmin.
    Pacientes (rol 4) caen a la clínica principal (1).
    """
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


def _is_global_super_admin(current_user: Usuario) -> bool:
    """Superadmin real: sin clínica Y con rol global (rol.id_clinica=None)."""
    if current_user is None or current_user.id_clinica is not None:
        return False
    rol = getattr(current_user, "rol", None)
    if rol is not None and getattr(rol, "id_clinica", None) is not None:
        return False
    if current_user.id_rol == 1:
        return True
    try:
        rol_name = (rol.nombre.strip().upper() if rol and getattr(rol, "nombre", None) else "")
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
        # Check if role name is ADMIN (o SUPER global con otro id)
        rol_name = current_user.rol.nombre.upper() if current_user.rol and current_user.rol.nombre else ""
        if rol_name not in ["ADMIN", "ADMINISTRADOR", "ADMINISTRACION"] and "SUPER" not in rol_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos administrativos.",
            )
    return current_user


def require_roles(allowed_roles: List[str]):
    """Allow access to users matching any of the specified roles (o Super Admin global)."""
    def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        # Bypass global: Super Administrador (rol global) accede a todo.
        if _is_global_super_admin(current_user):
            return current_user
        role_name = current_user.rol.nombre.upper() if current_user.rol else ""
        allowed_upper = [r.upper() for r in allowed_roles]
        
        # If admin is in allowed and user has admin id
        if "ADMIN" in allowed_upper and current_user.id_rol == ADMIN_ROLE_ID:
            return current_user

        if role_name not in allowed_upper:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso denegado. Se requiere uno de los siguientes roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker
