"""Scoped SQL aggregates for CU22. Never load a full Medico ORM entity."""

from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, case, func, literal, select
from sqlalchemy.orm import Session

from app.modules.appointments.models import Cita, Especialidad, Medico
from app.modules.auth.models import Usuario
from app.modules.medical_records.hce.models import Consulta, HistoriaClinica

from .catalog import MAX_EXPORT_ROWS, MODALITIES, NO_SHOW, REPORTS, STATES, Report
from .schemas import QueryRequest, QueryResponse


def _invalid(message: str):
    raise HTTPException(422, message)


def _report(report_id: str) -> Report:
    if report_id == "ausentismo":
        _invalid("SIN_ESTADO_AUSENCIA")
    report = REPORTS.get(report_id)
    if report is None:
        _invalid("Reporte no permitido")
    return report


def _scoped_doctor(db: Session, clinic_id: int, doctor_id: int) -> bool:
    m, u = Medico.__table__, Usuario.__table__
    stmt = select(m.c.id_medico).select_from(
        m.join(u, m.c.id_usuario == u.c.id_usuario)
    ).where(m.c.id_medico == doctor_id, u.c.id_clinica == clinic_id)
    return db.execute(stmt).first() is not None


def _scoped_specialty(db: Session, clinic_id: int, specialty_id: int) -> bool:
    c, m, u = Cita.__table__, Medico.__table__, Usuario.__table__
    stmt = select(c.c.id_especialidad).select_from(
        c.join(m, c.c.id_medico == m.c.id_medico).join(u, m.c.id_usuario == u.c.id_usuario)
    ).where(c.c.id_especialidad == specialty_id, u.c.id_clinica == clinic_id).limit(1)
    return db.execute(stmt).first() is not None


def options(db: Session, clinic_id: int) -> dict:
    m, u, c, e = Medico.__table__, Usuario.__table__, Cita.__table__, Especialidad.__table__
    doctors = db.execute(
        select(m.c.id_medico, u.c.nombres, u.c.apellidos).select_from(
            m.join(u, m.c.id_usuario == u.c.id_usuario)
        ).where(u.c.id_clinica == clinic_id).order_by(u.c.apellidos, u.c.nombres, m.c.id_medico)
    ).all()
    specialties = db.execute(
        select(e.c.id_especialidad, e.c.nombre).distinct().select_from(
            c.join(m, c.c.id_medico == m.c.id_medico)
            .join(u, m.c.id_usuario == u.c.id_usuario)
            .join(e, c.c.id_especialidad == e.c.id_especialidad)
        ).where(u.c.id_clinica == clinic_id).order_by(e.c.nombre, e.c.id_especialidad)
    ).all()
    return {
        "medicos": [{"id_medico": row[0], "nombre": f"{row[1]} {row[2]}".strip()} for row in doctors],
        "especialidades": [{"id_especialidad": row[0], "nombre": row[1]} for row in specialties],
    }


def normalize(db: Session, clinic_id: int, request: QueryRequest) -> tuple[QueryRequest, Report]:
    report = _report(request.reporte)
    groups = request.agrupacion
    if len(set(groups)) != len(groups) or any(item not in report.dimensions for item in groups):
        _invalid("Agrupación desconocida o duplicada")
    columns = request.columnas or [*groups, report.primary]
    if (
        len(set(columns)) != len(columns)
        or any(item not in report.dimensions + report.metrics for item in columns)
        or any(item not in columns for item in groups)
        or report.primary not in columns
        or any(item in report.dimensions and item not in groups for item in columns)
    ):
        _invalid("Columnas incompatibles, desconocidas o duplicadas")
    sorts = request.orden or [
        {"campo": item, "direccion": "asc"} for item in groups
    ]
    if len({item.campo if hasattr(item, "campo") else item["campo"] for item in sorts}) != len(sorts):
        _invalid("Orden duplicado")
    for item in sorts:
        field = item.campo if hasattr(item, "campo") else item["campo"]
        if field not in columns or (field in report.dimensions and field not in groups):
            _invalid("Orden incompatible o desconocido")
    filter_fields: set[str] = set()
    for item in request.filtros:
        if item.campo not in report.filters or item.campo in filter_fields:
            _invalid("Filtro desconocido o duplicado")
        filter_fields.add(item.campo)
        value = item.valor
        if item.campo in {"id_medico", "id_especialidad"}:
            if type(value) is not int or value <= 0:
                _invalid("ID de filtro inválido")
            exists = (
                _scoped_doctor(db, clinic_id, value) if item.campo == "id_medico"
                else _scoped_specialty(db, clinic_id, value)
            )
            if not exists:
                raise HTTPException(404, "Opción no encontrada")
        elif item.campo == "estado":
            if type(value) is not str or value not in STATES:
                _invalid("Estado no permitido")
        elif item.campo == "modalidad":
            if type(value) is not str or value not in MODALITIES:
                _invalid("Modalidad no permitida")
    normalized = QueryRequest(
        reporte=request.reporte, periodo=request.periodo, filtros=request.filtros,
        columnas=columns, agrupacion=groups, orden=sorts,
        pagina=request.pagina, tamano_pagina=request.tamano_pagina,
    )
    return normalized, report


def _modality(c):
    kind = func.nullif(func.upper(func.trim(c.c.tipo_consulta)), "")
    mode = func.nullif(func.upper(func.trim(c.c.modalidad)), "")
    value = func.coalesce(kind, mode)
    return case(
        (and_(kind.is_not(None), mode.is_not(None), kind != mode), literal("CONFLICTO")),
        (and_(kind.is_(None), mode.is_(None)), literal("DESCONOCIDA")),
        (value.in_(("PRESENCIAL", "TELEMEDICINA")), value),
        else_=literal("OTRA"),
    )


def _base(db: Session, clinic_id: int, definition: QueryRequest, report: Report):
    c, m, u = Cita.__table__, Medico.__table__, Usuario.__table__
    fields = [
        c.c.id_cita.label("id_cita"), c.c.id_paciente.label("id_paciente"),
        c.c.id_medico.label("id_medico"), c.c.id_especialidad.label("id_especialidad"),
        func.upper(func.coalesce(c.c.estado, "DESCONOCIDO")).label("estado"),
        _modality(c).label("modalidad"),
    ]
    if report.source == "consultas":
        q, h = Consulta.__table__, HistoriaClinica.__table__
        source = (
            q.join(h, q.c.id_historia == h.c.id_historia)
            .join(c, q.c.id_cita == c.c.id_cita)
            .join(m, c.c.id_medico == m.c.id_medico)
            .join(u, m.c.id_usuario == u.c.id_usuario)
        )
        fields.append(func.date(q.c.fecha_consulta).label("fecha"))
        conditions = [
            q.c.id_clinica == clinic_id, h.c.id_clinica == clinic_id,
            h.c.id_paciente == c.c.id_paciente, q.c.id_medico == c.c.id_medico,
            u.c.id_clinica == clinic_id,
            q.c.fecha_consulta >= datetime.combine(definition.periodo.desde, time.min),
            q.c.fecha_consulta < datetime.combine(definition.periodo.hasta + timedelta(days=1), time.min),
        ]
    else:
        source = c.join(m, c.c.id_medico == m.c.id_medico).join(
            u, m.c.id_usuario == u.c.id_usuario
        )
        fields.append(func.date(c.c.fecha_cita).label("fecha"))
        conditions = [
            u.c.id_clinica == clinic_id,
            c.c.fecha_cita >= definition.periodo.desde,
            c.c.fecha_cita <= definition.periodo.hasta,
        ]
    raw = select(*fields).select_from(source).where(*conditions).subquery("raw")
    filters = [raw.c[item.campo] == item.valor for item in definition.filtros]
    return select(*[raw.c[name] for name in raw.c.keys()]).where(*filters).subquery("filtrado")


def _metric_expressions(base):
    return {
        "encuentros": func.count(func.distinct(base.c.id_cita)),
        "citas": func.count(func.distinct(base.c.id_cita)),
        "pacientes_unicos": func.count(func.distinct(base.c.id_paciente)),
        "cancelaciones": func.count(func.distinct(
            case((base.c.estado == "CANCELADA", base.c.id_cita))
        )),
    }


def query(db: Session, clinic_id: int, request: QueryRequest, *, export: bool = False) -> QueryResponse:
    definition, report = normalize(db, clinic_id, request)
    base = _base(db, clinic_id, definition, report)
    metrics = _metric_expressions(base)
    global_values = db.execute(
        select(*[metrics[name].label(name) for name in report.metrics]).select_from(base)
    ).mappings().one()
    available = {
        name: {"disponible": True, "valor": int(global_values[name]), "causa": None}
        for name in report.metrics
    }
    available["ausentismo"] = dict(NO_SHOW)
    source_count = int(global_values["encuentros" if report.source == "consultas" else "citas"])
    dimensions = [base.c[name] for name in definition.agrupacion]
    grouped = select(
        *[col.label(name) for col, name in zip(dimensions, definition.agrupacion)],
        *[metrics[name].label(name) for name in report.metrics],
    ).select_from(base)
    if dimensions:
        grouped = grouped.group_by(*dimensions)
    grouped = grouped.subquery("grupos")
    if dimensions:
        total = int(db.execute(select(func.count()).select_from(grouped)).scalar_one())
    else:
        total = 1 if source_count else 0
    if export and total > MAX_EXPORT_ROWS:
        raise HTTPException(413, f"La exportación supera {MAX_EXPORT_ROWS} filas")
    order_items = []
    used = set()
    for item in definition.orden:
        col = grouped.c[item.campo]
        order_items.append(col.desc() if item.direccion == "desc" else col.asc())
        used.add(item.campo)
    for name in definition.agrupacion:
        if name not in used:
            order_items.append(grouped.c[name].asc())
    stmt = select(grouped)
    if order_items:
        stmt = stmt.order_by(*order_items)
    if export:
        stmt = stmt.limit(MAX_EXPORT_ROWS + 1)
    else:
        stmt = stmt.limit(definition.tamano_pagina).offset((definition.pagina - 1) * definition.tamano_pagina)
    records = db.execute(stmt).mappings().all() if total else []
    if export and len(records) > MAX_EXPORT_ROWS:
        raise HTTPException(413, f"La exportación supera {MAX_EXPORT_ROWS} filas")
    rows = [
        {
            column: value.isoformat() if isinstance(value, (date, datetime)) else value
            for column in definition.columnas
            for value in (record[column],)
        }
        for record in records
    ]
    warnings = ["Ausentismo no calculable: SIN_ESTADO_AUSENCIA."]
    if report.source == "consultas":
        warnings.append("Encuentros registrados no equivale al total exhaustivo histórico de atenciones.")
    if definition.agrupacion and "pacientes_unicos" in report.metrics:
        warnings.append("Los pacientes únicos globales no se obtienen sumando grupos.")
    return QueryResponse(
        definicion=definition, semantica=report.semantics, metricas=available,
        total=total, filas=rows, advertencias=warnings,
        generado_en=datetime.now(timezone.utc),
    )
