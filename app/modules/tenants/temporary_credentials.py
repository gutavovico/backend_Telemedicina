from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.auth.models import Usuario
from app.modules.tenants.models import TenantRequest


def get_must_change_credential(
    db: Session,
    id_usuario: int,
) -> Optional[TenantRequest]:
    """Obtiene la solicitud aprobada que aún exige cambiar la contraseña."""
    try:
        user = db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()
        if not user or user.id_clinica is None:
            return None
        return db.query(TenantRequest).filter(
            TenantRequest.id_clinica == user.id_clinica,
            TenantRequest.credentials_issued.is_(True),
            TenantRequest.temporary_password_changed_at.is_(None),
        ).order_by(TenantRequest.decision_fecha.desc()).first()
    except OperationalError:
        # Compatibilidad con bases legacy en pruebas o despliegues previos a 019.
        db.rollback()
        return None


def user_must_change_password(db: Session, id_usuario: int) -> bool:
    return get_must_change_credential(db, id_usuario) is not None


def credential_is_expired(credential: TenantRequest) -> bool:
    expires_at = credential.temporary_password_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at is None or datetime.now(timezone.utc) >= expires_at
