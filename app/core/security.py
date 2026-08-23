import bcrypt
# Fix passlib compatibility with bcrypt >= 4.0.0
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("about", (), {"__version__": getattr(bcrypt, "__version__", "4.0.0")})

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status
from app.core.config import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a short-lived access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a long-lived refresh token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_REFRESH_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token no válido (tipo incorrecto)",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_refresh_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT refresh token."""
    try:
        payload = jwt.decode(token, settings.JWT_REFRESH_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token no válido",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Recuperación de contraseña por código de 6 dígitos (CU23)
# El código se deriva con HMAC-SHA256 usando el id del usuario, un secreto y
# una ventana de tiempo (bucket). No requiere tablas ni migraciones.
# ---------------------------------------------------------------------------

_RESET_ATTEMPTS: Dict[int, Dict[str, Any]] = {}


def _reset_bucket(now_ts: int, ttl_seconds: int) -> int:
    """Devuelve el bucket (ventana) al que pertenece el instante dado."""
    return now_ts // ttl_seconds


def _reset_code_for_bucket(user_id: int, bucket: int) -> str:
    """Genera el código de 6 dígitos para un usuario en un bucket concreto."""
    message = f"{user_id}:{bucket}".encode("utf-8")
    digest = hmac.new(
        settings.JWT_RESET_SECRET_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    # Convierte parte del digest en un entero de 6 dígitos (000000-999999)
    return f"{int(digest[:8], 16) % 1000000:06d}"


def _codes_match(provided: str, expected: str) -> bool:
    """Comparación de códigos en tiempo constante."""
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _check_reset_lockout(user_id: int) -> None:
    """Si el usuario está en periodo de bloqueo, rechaza la verificación."""
    attempt = _RESET_ATTEMPTS.get(user_id)
    if not attempt:
        return
    failed = attempt.get("failed", 0)
    lock_until = attempt.get("lock_until")
    if failed >= settings.RESET_CODE_MAX_ATTEMPTS and lock_until:
        if time.time() < lock_until:
            minutes_left = int((lock_until - time.time()) // 60) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Demasiados intentos fallidos. Intenta de nuevo en {minutes_left} min.",
            )
        # El bloqueo ya venció: reinicia el contador
        _RESET_ATTEMPTS.pop(user_id, None)


def generate_reset_code(user_id: int) -> str:
    """Genera el código de recuperación vigente para un usuario."""
    now_ts = int(time.time())
    bucket = _reset_bucket(now_ts, settings.RESET_CODE_TTL_MINUTES * 60)
    return _reset_code_for_bucket(user_id, bucket)


def verify_reset_code(user_id: int, code: str) -> bool:
    """Valida el código en la ventana actual o en la anterior (tolerancia)."""
    if not code or not code.isdigit() or len(code) != 6:
        return False

    _check_reset_lockout(user_id)

    now_ts = int(time.time())
    bucket = _reset_bucket(now_ts, settings.RESET_CODE_TTL_MINUTES * 60)
    candidates = [
        _reset_code_for_bucket(user_id, bucket),
        _reset_code_for_bucket(user_id, bucket - 1),
    ]

    if any(_codes_match(code, candidate) for candidate in candidates):
        _RESET_ATTEMPTS.pop(user_id, None)
        return True

    # Registra intento fallido para el bloqueo anti fuerza bruta
    attempt = _RESET_ATTEMPTS.setdefault(user_id, {"failed": 0, "lock_until": None})
    attempt["failed"] = attempt.get("failed", 0) + 1
    if attempt["failed"] >= settings.RESET_CODE_MAX_ATTEMPTS:
        attempt["lock_until"] = time.time() + settings.RESET_CODE_LOCKOUT_MINUTES * 60
    return False
