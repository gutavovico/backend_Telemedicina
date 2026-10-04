"""CU22-specific authorization based on the authenticated user's clinic."""

import unicodedata

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Usuario


def _normalized_role(name: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", name.strip().upper())
        if not unicodedata.combining(c)
    )


def require_report_admin(
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> int:
    role = user.rol
    if (
        role is None
        or (user.estado or "").lower() != "activo"
        or _normalized_role(role.nombre) not in {"ADMIN", "ADMINISTRADOR", "ADMINISTRACION"}
        or (role.estado or "").lower() != "activo"
        or user.id_clinica is None
        or (role.id_clinica is not None and role.id_clinica != user.id_clinica)
    ):
        raise HTTPException(403, "Se requiere ADMIN activo de una clínica")
    clinic = Clinica.__table__
    status = db.execute(
        select(clinic.c.estado).where(clinic.c.id_clinica == user.id_clinica)
    ).scalar_one_or_none()
    if status is None or status.lower() != "activo":
        raise HTTPException(403, "Se requiere una clínica activa")
    return user.id_clinica
