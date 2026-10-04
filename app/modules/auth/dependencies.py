from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.auth.models import Usuario
from app.modules.auth.service import get_user_by_id
from app.modules.auth.session_service import enforce_inactivity

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Usuario:
    """Dependency to retrieve the authenticated user from the Bearer JWT token."""
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
    # los access tokens emitidos hasta entonces. Sin esta comparacion, un token
    # "cerrado" seguiria funcionando hasta caducar por `exp`.
    #
    # Se evalua ANTES que la inactividad: un logout explicito revoca tambien el
    # `jti`, asi que si se invirtiera el orden, `/auth/me` responderia "sesion
    # cerrada por inactividad" y el frontend avisaria al usuario de un tiempo
    # expirado que en realidad fue un cierre manual.
    token_version = payload.get("token_version")
    if token_version is not None and int(token_version) != int(user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesion cerrada: el token ya no es valido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # CU23: ventana de inactividad por sesion. Se evalua con el usuario ya
    # cargado para poder validar tambien el tenant: si la sesion quedo abierta y
    # el usuario cambio de clinica, la sesion vieja no debe seguir operando.
    # `get_current_user` refresca `ultima_actividad`, que es lo que hace que la
    # actividad real del usuario mantenga viva su sesion.
    enforce_inactivity(
        db,
        payload.get("jti"),
        user_id,
        id_clinica=user.id_clinica,
    )

    if user.estado.lower() != "activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario est? inactiva o suspendida",
        )

    return user


def get_current_tenant_id(
    current_user: Usuario = Depends(get_current_user),
) -> Optional[int]:
    """Resolve el tenant (clinica) del usuario autenticado.

    El tenant SIEMPRE se deriva de `Usuario.id_clinica` en base de datos; nunca
    se acepta desde el body, la query ni un header, para evitar inyeccion de
    tenant. Si el usuario no tiene clinica asignada se responde 403 porque el
    alcance por tenant no puede determinarse.
    """
    tenant_id = current_user.id_clinica
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene una clinica (tenant) asignada",
        )
    return int(tenant_id)
