from datetime import datetime, timezone
from sqlalchemy import select, update, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.audit import registrar_auditoria
from app.modules.auth.models import Plan, VersionPlan
from .schemas import PlanCreate, VersionCreate, PlanResponse, VersionResponse, PlanPage, VersionPage


class PlanError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        self.status, self.code, self.detail = status, code, detail


def _plan(db: Session, plan_id: int, *, lock=False):
    stmt = select(Plan).where(Plan.id == plan_id).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update()
    plan = db.scalar(stmt)
    if plan is None:
        raise PlanError(404, "PLAN_NOT_FOUND", "Plan no encontrado")
    return plan


def _response(db, plan):
    version = db.scalar(select(VersionPlan).where(VersionPlan.plan_id == plan.id, VersionPlan.numero == plan.version_actual))
    return PlanResponse(id=plan.id, codigo=plan.codigo, activo=plan.activo,
                        version_actual=plan.version_actual, creado_en=plan.creado_en,
                        actualizado_en=plan.actualizado_en, version=VersionResponse.model_validate(version))


def detail(db, plan_id):
    return _response(db, _plan(db, plan_id))


def list_plans(db, q, estado, page, per_page):
    conditions = []
    if estado:
        conditions.append(Plan.activo == (estado == "ACTIVO"))
    if q:
        term = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(Plan.codigo.ilike(term, escape="\\"), VersionPlan.nombre.ilike(term, escape="\\")))
    join = (VersionPlan.plan_id == Plan.id) & (VersionPlan.numero == Plan.version_actual)
    total = db.scalar(select(func.count()).select_from(Plan).join(VersionPlan, join).where(*conditions))
    rows = db.execute(select(Plan, VersionPlan).join(VersionPlan, join).where(*conditions)
                      .order_by(Plan.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    items = [PlanResponse(id=p.id, codigo=p.codigo, activo=p.activo, version_actual=p.version_actual,
                          creado_en=p.creado_en, actualizado_en=p.actualizado_en,
                          version=VersionResponse.model_validate(v)) for p, v in rows]
    return PlanPage(items=items, total=total, page=page, per_page=per_page)


def history(db, plan_id, page, per_page):
    _plan(db, plan_id)
    predicate = VersionPlan.plan_id == plan_id
    total = db.scalar(select(func.count()).select_from(VersionPlan).where(predicate))
    versions = db.scalars(select(VersionPlan).where(predicate).order_by(VersionPlan.numero.desc())
                          .offset((page - 1) * per_page).limit(per_page)).all()
    return VersionPage(items=[VersionResponse.model_validate(v) for v in versions], total=total, page=page, per_page=per_page)


def version_detail(db, plan_id, number):
    _plan(db, plan_id)
    version = db.scalar(select(VersionPlan).where(VersionPlan.plan_id == plan_id, VersionPlan.numero == number))
    if version is None:
        raise PlanError(404, "PLAN_VERSION_NOT_FOUND", "Versión no encontrada")
    return VersionResponse.model_validate(version)


def _version_data(data):
    result = data.model_dump(exclude={"codigo", "version_base"})
    # JSON never receives Decimal or binary float.
    result["tarifas_excedentes"] = [t.model_dump(mode="json") for t in data.tarifas_excedentes]
    # model_dump serializes price through field_serializer; restore Decimal for Numeric.
    result["precio_mensual"] = data.precio_mensual
    return result


def _audit(db, user_id, plan_id, action, before, after, ip):
    registrar_auditoria(db, id_usuario=user_id, id_clinica=None, tabla_afectada="planes",
                       registro_id=plan_id, accion=action, descripcion="CU34: catálogo global",
                       datos_anteriores=before, datos_nuevos=after, direccion_ip=ip)


def create(db: Session, data: PlanCreate, user_id: int, ip=None):
    try:
        plan = Plan(codigo=data.codigo, activo=True, version_actual=1)
        db.add(plan)
        db.flush()
        db.add(VersionPlan(plan_id=plan.id, numero=1, creado_por=user_id, **_version_data(data)))
        db.flush()
        response = _response(db, plan)
        _audit(db, user_id, plan.id, "INSERT", None, response.model_dump(mode="json"), ip)
        db.commit()
        return response
    except IntegrityError as exc:
        db.rollback()
        if db.scalar(select(Plan.id).where(Plan.codigo == data.codigo)) is not None:
            db.rollback()
            raise PlanError(409, "PLAN_CODE_EXISTS", "Ya existe un plan con ese código") from exc
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def new_version(db: Session, plan_id: int, data: VersionCreate, user_id: int, ip=None):
    try:
        plan = _plan(db, plan_id, lock=True)
        if not plan.activo:
            raise PlanError(409, "PLAN_INACTIVE", "El plan está desactivado y no puede editarse")
        if plan.version_actual != data.version_base:
            raise PlanError(409, "PLAN_STALE_VERSION", "El plan cambió. Recargue las condiciones antes de editar")
        before = _response(db, plan).model_dump(mode="json")
        number = data.version_base + 1
        result = db.execute(update(Plan).where(Plan.id == plan_id, Plan.activo.is_(True), Plan.version_actual == data.version_base)
                            .values(version_actual=number, actualizado_en=datetime.now(timezone.utc)))
        if result.rowcount != 1:
            raise PlanError(409, "PLAN_CONCURRENT_CHANGE", "El plan cambió durante la operación")
        db.add(VersionPlan(plan_id=plan_id, numero=number, creado_por=user_id, **_version_data(data)))
        db.flush()
        response = detail(db, plan_id)
        _audit(db, user_id, plan_id, "UPDATE", before, response.model_dump(mode="json"), ip)
        db.commit()
        return response
    except IntegrityError as exc:
        db.rollback()
        raise PlanError(409, "PLAN_CONCURRENT_CHANGE", "Otra operación modificó el plan. Recargue e intente nuevamente") from exc
    except Exception:
        db.rollback()
        raise


def deactivate(db: Session, plan_id: int, user_id: int, ip=None):
    try:
        plan = _plan(db, plan_id, lock=True)
        before = _response(db, plan)
        if not plan.activo:
            return before
        result = db.execute(update(Plan).where(Plan.id == plan_id, Plan.activo.is_(True), Plan.version_actual == plan.version_actual)
                            .values(activo=False, actualizado_en=datetime.now(timezone.utc)))
        if result.rowcount != 1:
            raise PlanError(409, "PLAN_CONCURRENT_CHANGE", "El plan cambió durante la operación")
        response = detail(db, plan_id)
        _audit(db, user_id, plan_id, "UPDATE", before.model_dump(mode="json"), response.model_dump(mode="json"), ip)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
