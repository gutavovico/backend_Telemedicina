from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    new_jti,
)
from app.modules.auth.schemas import (
    UsuarioCreate,
    UsuarioResponse,
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    LogoutRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    SessionStatusResponse,
)
from app.modules.auth.models import Usuario, SesionActiva
from app.modules.auth.session_service import (
    enforce_inactivity,
    revoke_session,
    session_status as auth_session_status,
)

# resolver el usuario completo.
bearer_scheme = HTTPBearer()
from app.modules.auth.service import (
    create_user,
    authenticate_user,
    get_user_by_id,
    request_password_reset,
    request_password_reset_sms,
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
        "email": user.correo,
        "nombres": user.nombres,
        "apellidos": user.apellidos,
        # CU01: el token debe incorporar la version de token del usuario.
        "token_version": user.token_version or 0,
        "rol": user.rol,  # Incluir rol para frontend (sidebar, permisos)
    }

    # CU23: un par de tokens por sesion. Se genera un unico `jti` que comparten
    # ambos tokens, de modo que acceso y refresh identifican la MISMA sesion y
    # basta revocar ese jti para cerrarla sin afectar a los demas dispositivos.
    jti = new_jti()
    token_payload["jti"] = jti

    access_token = create_access_token(data=token_payload)
    refresh_token = create_refresh_token(data=token_payload)

    # Registro de la sesion para poder medir su inactividad mas adelante.
    db.add(
        SesionActiva(
            jti=jti,
            id_usuario=user.id_usuario,
            id_clinica=user.id_clinica,
        )
    )
    db.commit()

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
    if not user or user.estado.lower() != "activo":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo o no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # CU24: un refresh emitido antes de un cierre de sesion debe rechazarse. Sin
    # esta comparacion, el logout solo inutilizaria los access tokens.
    if _token_version_desactualizado(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesion cerrada: el token de refresco ya no es valido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Se conserva el mismo `jti` y el mismo `token_version`: es la MISMA sesion,
    # no una nueva. Si se emitiera un `jti` distinto, la sesion nueva no tendria
    # fila en `sesiones_activas` y se quedaria sin control de inactividad.
    new_payload = {
        "sub": str(user.id_usuario),
        "email": user.correo,
        "nombres": user.nombres,
        "apellidos": user.apellidos,
        "token_version": user.token_version or 0,
        "rol": user.rol,
        "jti": payload.get("jti") or new_jti(),
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
    summary="Cerrar sesion y revocar los tokens",
    description=(
        "Incrementa `token_version` del usuario, con lo que quedan invalidos "
        "todos los access y refresh tokens emitidos hasta ahora, y revoca la "
        "sesion (`jti`) asociada. Es el cierre GLOBAL de CU24: a diferencia del cierre "
        "por inactividad de CU23, aqui tb se caen las demas sesiones del mismo "
        "usuario en otros dispositivos."
    ),
)
def logout(
    request_data: LogoutRequest,
    db: Session = Depends(get_db),
) -> Response:
    """Cierra la sesion de forma idempotente y global (CU24)."""
    try:
        payload = decode_refresh_token(request_data.refresh_token)
    except HTTPException:
        # Cerrar sesion nunca debe fallar por un token caducado: el objetivo es
        # justamente dejar al cliente sin sesion, y el cliente limpia su
        # almacenamiento local igualmente.
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    user_id = payload.get("sub")
    if user_id is not None:
        try:
            user = get_user_by_id(db, int(user_id))
        except ValueError:
            user = None
        if user is not None:
            # Solo se incrementa si el token corresponde a la version vigente.
            # Asi, reintentar el logout (red inestable, doble toque) es
            # idempotente y no invalida tokens emitidos despues del cierre, que
            # es justo lo que se quiere preservar.
            claim = payload.get("token_version")
            version_actual = int(user.token_version or 0)
            if claim is None or int(claim) == version_actual:
                user.token_version = version_actual + 1
                db.commit()

    # Ademas se revoca la sesion concreta, para que no quede viva en
    # `sesiones_activas` ni en `token_blacklist`.
    jti = payload.get("jti")
    if jti:
        revoke_session(db, jti)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _token_version_desactualizado(payload: dict, user: Usuario) -> bool:
    """`True` si el claim `token_version` del token no coincide con la BD.

    Un token sin `token_version` (emitido antes de este requisito) se acepta:
    no se quiere expulsar de golpe a las sesiones ya abiertas.
    """
    claim = payload.get("token_version")
    if claim is None:
        return False
    try:
        return int(claim) != int(user.token_version or 0)
    except (TypeError, ValueError):
        return True


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
    """Solicita el envío de un código de recuperación por el canal indicado.

    El canal por defecto sigue siendo el correo, de modo que un cliente que no
    envíe `canal` conserva el comportamiento anterior (CU23).
    """
    if data.canal == "sms":
        debug_code = request_password_reset_sms(db=db, correo=data.correo)
    else:
        debug_code = request_password_reset(db=db, correo=data.correo)

    response = ForgotPasswordResponse(detail=FORGOT_PASSWORD_GENERIC)
    if debug_code:
        # Modo desarrollo: exponer el código para facilitar la demo sin SMTP/SMS
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


@router.get(
    "/session",
    response_model=SessionStatusResponse,
    summary="Consultar el tiempo restante de sesion",
    description=(
        "Devuelve los segundos restantes antes del cierre automatico por "
        "inactividad (CU23). El cliente lo usa para el aviso con cuenta "
        "regresiva y para reconciliar su reloj al recuperar el foco. Esta "
        "consulta NO renueva la sesion: para eso esta POST /session/continue."
    ),
)
def session_status(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> SessionStatusResponse:
    """Inactividad restante de la sesion que porta el token.

    Una sesion revocada o vencida responde 401 en vez de anunciar una ventana
    completa, porque `session_status` aplica la misma validacion que el resto de
    las peticiones autenticadas.
    """
    payload = decode_access_token(credentials.credentials)
    estado = auth_session_status(db, payload.get("jti"), int(payload["sub"]))
    return SessionStatusResponse(**estado)


@router.post(
    "/session/continue",
    response_model=SessionStatusResponse,
    summary="Renovar la sesion por inactividad",
    description=(
        "Renueva `ultima_actividad` y devuelve el nuevo tiempo restante. Es la "
        "operacion que ejecuta el boton \"Seguir conectado\" del aviso de "
        "inactividad (CU23). Reutiliza `get_current_user`, de modo que tambien "
        "valida que la cuenta siga activa."
    ),
)
def session_continue(
    current_user: Usuario = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> SessionStatusResponse:
    """Renueva la sesion actual si sigue viva.

    `get_current_user` ya aplica `enforce_inactivity` con refresco de
    `ultima_actividad`, asi que llegar aqui significa que la sesion es valida.
    """
    payload = decode_access_token(credentials.credentials)
    jti = payload.get("jti")
    if jti:
        restante = enforce_inactivity(
            db, jti, int(current_user.id_usuario), id_clinica=current_user.id_clinica
        )
        if restante is not None:
            return SessionStatusResponse(
                segundos_restantes=restante,
                ventana_segundos=settings.INACTIVITY_TIMEOUT_MINUTES * 60,
                aviso_segundos=settings.INACTIVITY_WARNING_SECONDS,
            )

