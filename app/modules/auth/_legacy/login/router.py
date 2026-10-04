from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token
from app.modules.auth.models import Usuario
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.login.schemas import (
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    UsuarioCreate,
    UsuarioResponse,
)
from app.modules.auth.login.service import (
    authenticate_user,
    create_user,
    get_user_by_id,
)

router = APIRouter(tags=["Autenticación - Login (CU01)"])


@router.post(
    "/register",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registro público de usuarios",
)
def register(user_data: UsuarioCreate, db: Session = Depends(get_db)):
    """Registra un nuevo usuario en la plataforma."""
    return create_user(db=db, user_data=user_data)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Inicio de sesión",
    description="Autentica usuario y emite tokens JWT con claim tenant_id y token_version.",
)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """Inicia sesión y genera access_token y refresh_token."""
    user = authenticate_user(db=db, correo=login_data.correo, password=login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.estado.lower() != "activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario está inactiva o suspendida",
        )

    token_payload = {
        "sub": str(user.id_usuario),
        "token_version": user.token_version,
        "email": user.correo,
        "nombres": user.nombres,
        "apellidos": user.apellidos,
        "tenant_id": str(user.id_clinica) if user.id_clinica else None,
    }

    access_token = create_access_token(data=token_payload)
    refresh_token = create_refresh_token(data=token_payload)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Renovar access token",
)
def refresh_token(request_data: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Renueva el token de acceso usando el token de actualización."""
    payload = decode_refresh_token(request_data.refresh_token)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de refresco inválido: falta sujeto",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de refresco inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(db, user_id)
    if not user or payload.get("token_version", 0) != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión cerrada o refresh token revocado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.estado.lower() != "activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario está inactiva o suspendida",
            headers={"WWW-Authenticate": "Bearer"},
        )

    new_payload = {
        "sub": str(user.id_usuario),
        "token_version": user.token_version,
        "email": user.correo,
        "nombres": user.nombres,
        "apellidos": user.apellidos,
        "tenant_id": str(user.id_clinica) if user.id_clinica else None,
    }

    new_access_token = create_access_token(data=new_payload)
    new_refresh_token = create_refresh_token(data=new_payload)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )


@router.get(
    "/me",
    response_model=UsuarioResponse,
    summary="Obtener perfil del usuario autenticado",
)
def get_me(current_user: Usuario = Depends(get_current_user)):
    """Devuelve los datos del usuario actual."""
    return {
        "id_usuario": current_user.id_usuario,
        "id_clinica": current_user.id_clinica,
        "tenant_id": str(current_user.id_clinica) if current_user.id_clinica else None,
        "id_rol": current_user.id_rol,
        "nombres": current_user.nombres,
        "apellidos": current_user.apellidos,
        "correo": current_user.correo,
        "telefono": current_user.telefono,
        "foto_perfil": current_user.foto_perfil,
        "estado": current_user.estado,
        "notificaciones_push": current_user.notificaciones_push,
        "notificaciones_email": current_user.notificaciones_email,
        "notificaciones_sms": current_user.notificaciones_sms,
        "fecha_creacion": current_user.fecha_creacion,
    }
