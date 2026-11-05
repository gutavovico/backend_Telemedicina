"""Read the shared CU34 catalog without granting catalog administration rights."""
from fastapi import HTTPException
from sqlalchemy import select
from app.modules.auth.models import Plan, VersionPlan


def available_version(db, version_id: int, *, lock=False) -> VersionPlan:
    stmt = (select(VersionPlan).join(Plan, Plan.id == VersionPlan.plan_id)
            .where(VersionPlan.id == version_id, Plan.activo.is_(True),
                   VersionPlan.numero == Plan.version_actual))
    if lock:
        stmt = stmt.with_for_update()
    version = db.scalar(stmt)
    if version is None:
        raise HTTPException(422, 'La versión no existe o no está disponible para contratar')
    return version


def available_versions(db):
    return db.scalars(select(VersionPlan).join(Plan, Plan.id == VersionPlan.plan_id)
        .where(Plan.activo.is_(True), VersionPlan.numero == Plan.version_actual)
        .order_by(VersionPlan.precio_mensual, Plan.id)).all()
