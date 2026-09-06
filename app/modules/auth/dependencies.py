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


def require_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Allow access only to users with the Administracion role."""
    if current_user.id_rol != ADMIN_ROLE_ID:
        # Check if role name is ADMIN
        if not (current_user.rol and current_user.rol.nombre.upper() in ["ADMIN", "ADMINISTRADOR", "ADMINISTRACION"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos administrativos.",
            )
    return current_user


def require_roles(allowed_roles: List[str]):
    """Allow access to users matching any of the specified roles."""
    def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
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
