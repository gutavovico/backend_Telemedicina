from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token
from app.modules.auth.schemas import (
    UsuarioCreate,
    UsuarioResponse,
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
)
from app.modules.auth.models import Usuario
from app.modules.auth.service import (
    create_user,
    authenticate_user,
    get_user_by_id,
    request_password_reset,
    reset_password,
    FORGOT_PASSWORD_GENERIC,
)
from app.modules.auth.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post(
    "/register",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registro público de usuarios",
    description="Permite a cualquier usuario nuevo registrarse en la plataforma."
)
def register(user_data: UsuarioCreate, db: Session = Depends(get_db)):
    """Registra un nuevo usuario en la base de datos."""
    return create_user(db=db, user_data=user_data)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Inicio de sesión",
    description="Autentica un usuario con correo y contraseña, y devuelve access_token y refresh_token."
)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """Inicia sesión y genera tokens JWT."""
    user = authenticate_user(db=db, correo=login_data.correo, password=login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Token payload
    token_payload = {
        "sub": str(user.id_usuario),
        "token_version": user.token_version,
        "email": user.correo,
        "nombres": user.nombres,
        "apellidos": user.apellidos,
    }

    access_token = create_access_token(data=token_payload)
    refresh_token = create_refresh_token(data=token_payload)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer"
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Renovar access token",
    description="Recibe un refresh_token válido y emite un nuevo par de tokens (access y refresh)."
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
    if user.estado != "activo":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo o no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    new_payload = {
        "sub": str(user.id_usuario),
        "token_version": user.token_version,
        "email": user.correo,
        "nombres": user.nombres,
        "apellidos": user.apellidos,
    }

    new_access_token = create_access_token(data=new_payload)
    new_refresh_token = create_refresh_token(data=new_payload)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer"
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar sesión",
    description="Revoca la sesión del usuario y todos sus tokens emitidos.",
)
def logout(request_data: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Revoca los tokens incrementando la versión de sesión del usuario."""
    payload = decode_refresh_token(request_data.refresh_token)
    user_id_str = payload.get("sub")
    try:
        user_id = int(user_id_str)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

    user = get_user_by_id(db, user_id)
    if user:
        user.token_version += 1
        db.commit()


@router.get(
    "/me",
    response_model=UsuarioResponse,
    summary="Obtener perfil del usuario autenticado",
    description="Devuelve la información del usuario autenticado a través del token JWT Bearer."
)
def get_me(current_user: Usuario = Depends(get_current_user)):
    """Devuelve los datos del usuario actual."""
    return current_user


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Solicitar código de recuperación de contraseña",
    description="Recibe un correo y envía un código de 6 dígitos para restablecer la contraseña (CU23). "
                "Siempre responde de forma genérica para no revelar correos registrados.",
)
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Solicita el envío de un código de recuperación al correo indicado."""
    debug_code = request_password_reset(db=db, correo=data.correo)
    response = ForgotPasswordResponse(detail=FORGOT_PASSWORD_GENERIC)
    if debug_code:
        # Modo desarrollo: exponer el código para facilitar la demo sin SMTP
        response.debug_code = debug_code
    return response


@router.post(
    "/reset-password",
    summary="Restablecer contraseña con código de recuperación",
    description="Valida el código de 6 dígitos y actualiza la contraseña del usuario (CU23).",
)
def reset_password_endpoint(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Restablece la contraseña validando el código de recuperación."""
    reset_password(
        db=db,
        correo=data.correo,
        codigo=data.codigo,
        nueva_password=data.nueva_password,
    )
    return {"detail": "Contraseña restablecida exitosamente."}
