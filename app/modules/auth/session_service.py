"""Control de inactividad por sesión (CU23).

La inactividad se mide sobre `sesiones_activas.ultima_actividad`, que se refresca
en cada petición autenticada. Al superar `INACTIVITY_TIMEOUT_MINUTES` se revoca
el `jti` de ESA sesión en `token_blacklist` y la petición se rechaza con 401.

La revocación es por `jti` y no un incremento de `token_version` (decision D2):
incrementar la versión cerraría también las sesiones legítimas del mismo usuario
en otros dispositivos, lo que contradice el escenario de la spec.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.auth.models import SesionActiva, TokenBlacklist


def _as_utc(value: datetime) -> datetime:
    """Normaliza a UTC.

    SQLite no guarda zona horaria, asi que una marca leida de la base llega
    ingenua; compararla contra `now(timezone.utc)` lanzaria TypeError y el
    calculo de inactividad fallaria en los tests.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_session(
    db: Session,
    jti: str,
    id_usuario: int,
    id_clinica: Optional[int] = None,
) -> Optional[SesionActiva]:
    """Sesion del usuario identificada por `jti`.

    Se filtra tambien por `id_usuario` para que un `jti` vǭlido de otro usuario
    no permita operar sobre su sesion, y por `id_clinica` cuando se conoce, para
    que una sesion no sobreviva a un cambio de clinica del usuario.
    """
    query = db.query(SesionActiva).filter(
        SesionActiva.jti == jti, SesionActiva.id_usuario == id_usuario
    )
    if id_clinica is not None:
        query = query.filter(SesionActiva.id_clinica == id_clinica)
    return query.one_or_none()


def is_revoked(db: Session, jti: str) -> bool:
    return db.query(TokenBlacklist.id).filter(TokenBlacklist.token == jti).first() is not None


def revoke_session(db: Session, jti: str) -> None:
    """Revoca una sesion concreta de forma idempotente."""
    if is_revoked(db, jti):
        return
    db.add(TokenBlacklist(token=jti))
    db.commit()


def _remaining_seconds(sesion: SesionActiva, now: datetime) -> int:
    limite = _as_utc(sesion.ultima_actividad) + timedelta(minutes=settings.INACTIVITY_TIMEOUT_MINUTES)
    return max(0, int((limite - now).total_seconds()))


def enforce_inactivity(
    db: Session,
    jti: Optional[str],
    id_usuario: int,
    id_clinica: Optional[int] = None,
    now: Optional[datetime] = None,
    touch: bool = True,
) -> Optional[int]:
    """Evalua la inactividad de la sesion y devuelve los segundos restantes.

    - Si el token no trae `jti` (emitido antes de este cambio) se acepta la
      peticion sin aplicar ventana: caduca sola por `exp` y no se quiere expulsar
      de golpe a las sesiones ya abiertas.
    - Si la sesion supero la ventana, se revoca y se marca `revocada_en`.
    - Si sigue viva, se refresca `ultima_actividad` respetando el intervalo
      minimo, salvo que `touch=False`.

    `touch=False` se usa en `GET /auth/session`: consultar el estado no debe
    contar como actividad, o el cliente podria alargar la sesion solo preguntando
    por ella. Renovar la sesion de verdad requiere `POST /auth/session/continue`.

    El llamante debe elevar el 401 correspondiente; aqui solo se lanza
    `HTTPException` cuando corresponde.
    """
    if not jti:
        return None

    now = now or datetime.now(timezone.utc)
    sesion = get_session(db, jti, id_usuario, id_clinica=id_clinica)

    if sesion is None:
        if id_clinica is not None:
            # Hay sesion con ese jti pero de otra clinica: el usuario cambio de
            # clinica con la sesion abierta, asi que no se le deja continuar.
            con_sesion = get_session(db, jti, id_usuario)
            if con_sesion is not None:
                con_sesion.revocada_en = now
                revoke_session(db, jti)
                _raise_session_closed()
        # El jti es valido pero no hay sesion registrada: se acepta para no
        # romper a tokens emitidos antes del despliegue de esta migracion.
        return None

    if is_revoked(db, jti):
        _raise_session_closed()

    if sesion.revocada_en is not None:
        _raise_session_closed()

    restante = _remaining_seconds(sesion, now)
    if restante <= 0:
        sesion.revocada_en = now
        revoke_session(db, jti)
        _raise_session_closed()

    # Refresco de la marca, acotado por el intervalo minimo configurado.
    if touch and (now - _as_utc(sesion.ultima_actividad)).total_seconds() >= (
        settings.INACTIVITY_TOUCH_INTERVAL_SECONDS
    ):
        sesion.ultima_actividad = now
        db.commit()
        # Tras renovar, lo que queda es la ventana completa: devolver el valor
        # previo haria que el boton "Seguir conectado" pareciera no tener efecto.
        return _remaining_seconds(sesion, now)

    return restante


def _raise_session_closed() -> None:
    from fastapi import HTTPException

    raise HTTPException(
        status_code=401,
        detail="Sesión cerrada por inactividad",
        headers={"WWW-Authenticate": "Bearer"},
    )


def session_status(db: Session, jti: Optional[str], id_usuario: int) -> dict:
    """Estado de la sesion para `GET /auth/session`.

    Reutiliza `enforce_inactivity` con `touch=False`, de modo que una sesion
    revocada o vencida devuelve 401 en vez de anunciar una ventana completa que
    el servidor no va a respetar, y consultar el estado no renueva la sesion.

    Un token sin `jti` no tiene sesion que medir, asi que recibe la ventana
    completa: es lo coherente con lo que `enforce_inactivity` le aplicara.
    """
    restante = enforce_inactivity(db, jti, id_usuario, touch=False)
    if restante is None:
        restante = settings.INACTIVITY_TIMEOUT_MINUTES * 60

    return {
        "segundos_restantes": restante,
        "ventana_segundos": settings.INACTIVITY_TIMEOUT_MINUTES * 60,
        "aviso_segundos": settings.INACTIVITY_WARNING_SECONDS,
    }


def purge_expired_revocations(db: Session, now: Optional[datetime] = None) -> int:
    """Borra revocaciones y sesiones ya vencidas.

    Un `jti` revocado deja de ser comprobable en cuanto caducan los tokens, y
    las filas de `sesiones_activas` irian creciendo sin limite en un despliegue
    real. Se purga lo que ya no sirve para rechazar nada.
    """
    now = now or datetime.now(timezone.utc)
    horizonte = now - timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    # Sesiones revocadas cuya ventana ya paso hace mucho tiempo.
    sesiones = (
        db.query(SesionActiva)
        .filter(SesionActiva.revocada_en.isnot(None), SesionActiva.revocada_en < horizonte)
        .all()
    )
    jtis_viejos = [s.jti for s in sesiones]
    db.query(SesionActiva).filter(SesionActiva.jti.in_(jtis_viejos)).delete(
        synchronize_session=False
    )

    # Revocaciones sin sesion, por si quedaron huerfanas.
    borradas = (
        db.query(TokenBlacklist)
        .filter(
            TokenBlacklist.revocada_en < horizonte,
            ~TokenBlacklist.token.in_(db.query(SesionActiva.jti)),
        )
        .delete(synchronize_session=False)
    )

    db.commit()
    return len(jtis_viejos) + borradas
