"""Reglas de dominio CU17, aisladas por clínica y ejecutadas en transacciones."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json

from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import registrar_auditoria
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.appointments.models import Medico
from app.modules.medical_records.models import Paciente
from app.modules.medical_records.hce.models import Consulta, Diagnostico, HistoriaClinica
from app.modules.medical_records.prescriptions.models import Receta, RecetaDetalle
from app.modules.medical_records.clinical_documents.dependencies import user_has_permission
from .models import (Tratamiento, TratamientoMedicamento, TratamientoDosis,
                     TratamientoEvento, TratamientoOperacionDosis)


class TreatmentError(Exception):
    def __init__(self, status_code: int, message: str, code: str = "TREATMENT_ERROR"):
        super().__init__(message)
        self.status_code, self.message, self.code = status_code, message, code


def fail(status_code, message, code):
    raise TreatmentError(status_code, message, f"TREATMENT_{code}")


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value):
    return as_utc(value).isoformat().replace("+00:00", "Z") if value else None


def authorize(db: Session, user: Usuario, tenant_id: int, permission: str):
    """Devuelve (rol, id del perfil) solo tras verificar clínica, rol y permiso."""
    if tenant_id is None or user.id_clinica != tenant_id or (user.estado or "").upper() != "ACTIVO":
        fail(403, "Acceso a tratamientos denegado", "FORBIDDEN")
    clinic = db.execute(select(Clinica.estado).where(Clinica.id_clinica == tenant_id)).scalar_one_or_none()
    role = db.execute(select(Rol.nombre, Rol.estado, Rol.id_clinica).where(Rol.id_rol == user.id_rol)).first()
    if not clinic or clinic.upper() != "ACTIVO" or not role or (role.estado or "").upper() != "ACTIVO":
        fail(403, "Acceso a tratamientos denegado", "FORBIDDEN")
    nombre = (role.nombre or "").strip().upper()
    if role.id_clinica not in (None, tenant_id) or nombre not in ("MEDICO", "PACIENTE") or not user_has_permission(db, user.id_rol, permission):
        fail(403, "Acceso a tratamientos denegado", "FORBIDDEN")
    if nombre == "MEDICO":
        profile = db.execute(select(Medico.id_medico).where(Medico.id_usuario == user.id_usuario)).scalar_one_or_none()
    else:
        profile = db.execute(select(Paciente.id_paciente).where(Paciente.id_usuario == user.id_usuario, Paciente.id_clinica == tenant_id)).scalar_one_or_none()
    if profile is None:
        fail(403, "Perfil clínico no disponible", "FORBIDDEN")
    return nombre, profile


def get_owned_plan(db, user, tenant_id, id_tratamiento, permission="treatments:read", for_update=False):
    role, profile = authorize(db, user, tenant_id, permission)
    query = select(Tratamiento).where(Tratamiento.id_clinica == tenant_id, Tratamiento.id_tratamiento == id_tratamiento)
    query = query.where(Tratamiento.id_paciente == profile) if role == "PACIENTE" else query.where(Tratamiento.id_medico == profile)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    plan = db.execute(query).scalar_one_or_none()
    if plan is None:
        fail(404, "Tratamiento no encontrado", "NOT_FOUND")
    return plan


def receta_vigente(db, plan, lock=False):
    if plan.id_receta is None:
        return True
    query = select(Receta.estado).where(Receta.id_clinica == plan.id_clinica, Receta.id_receta == plan.id_receta)
    if lock:
        query = query.with_for_update()
    estado = db.execute(query).scalar_one_or_none()
    return estado == "EMITIDA"


def estado_efectivo(db, plan):
    if plan.estado == "ACTIVO" and not receta_vigente(db, plan):
        return "SUSPENDIDO_POR_RECETA"
    return plan.estado


def _active(db, plan):
    if plan.estado != "ACTIVO" or not receta_vigente(db, plan, lock=True):
        fail(409, "El tratamiento no está activo", "CONFLICT")


def _occurrence(day, hour, zone):
    local = datetime.combine(day, time.fromisoformat(hour))
    options = []
    for fold in (0, 1):
        value = local.replace(tzinfo=zone, fold=fold)
        utc = value.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == local and utc not in options:
            options.append(utc)
    if len(options) != 1:
        fail(422, "Hora local inexistente o ambigua en la zona horaria", "VALIDATION")
    return options[0]


def validar_pauta(inicio, fin, horas, zona):
    zone = ZoneInfo(zona)
    day = inicio
    while day <= fin:
        for hour in horas:
            _occurrence(day, hour, zone)
        if day == fin:
            break
        day += timedelta(days=1)


def intervalo(horas):
    minutes = [int(h[:2]) * 60 + int(h[3:]) for h in horas]
    diffs = [(minutes[(i + 1) % len(minutes)] - x) % 1440 or 1440 for i, x in enumerate(minutes)]
    return diffs[0] / 60 if len(set(diffs)) == 1 else None


def _event(db, plan, user, role, ip, action, *, dose=None, med=None, before=None, after=None,
           note=None, effective=None, key_hash=None, request_hash=None, response=None):
    event = TratamientoEvento(id_clinica=plan.id_clinica, id_tratamiento=plan.id_tratamiento,
        id_dosis=dose.id_dosis if dose else None, id_medicamento_plan=med.id_medicamento_plan if med else None,
        accion=action, estado_anterior=before, estado_nuevo=after, id_usuario=user.id_usuario,
        rol_actor=role, direccion_ip=ip, nota=note, efectiva_en_utc=effective,
        ocurrida_en_utc=now_utc(), idempotencia_hash=key_hash, request_hash=request_hash, respuesta_json=response)
    db.add(event)
    db.flush()
    table = "tratamiento_dosis" if dose else "tratamiento_medicamentos" if med else "tratamientos"
    record_id = dose.id_dosis if dose else med.id_medicamento_plan if med else plan.id_tratamiento
    operation = "INSERT" if action == "CREAR_TRATAMIENTO" else "UPDATE"
    if action == "EVOLUCION_TRATAMIENTO":
        table, record_id, operation = "tratamiento_eventos", event.id_evento, "INSERT"
    registrar_auditoria(db, id_usuario=user.id_usuario, id_clinica=plan.id_clinica,
        tabla_afectada=table, registro_id=record_id,
        accion=operation, descripcion=action, datos_anteriores={"estado": before} if before else None,
        datos_nuevos={"estado": after, "rol_actor": role} if after else {"rol_actor": role}, direccion_ip=ip)
    return event


def _audit_read(db, user, tenant_id, action, ip, plan_id=None):
    registrar_auditoria(db, id_usuario=user.id_usuario, id_clinica=tenant_id,
        tabla_afectada="tratamientos", registro_id=plan_id, accion="SELECT",
        descripcion=action, direccion_ip=ip)


def _medicamentos(db, plan):
    return db.execute(select(TratamientoMedicamento).where(
        TratamientoMedicamento.id_clinica == plan.id_clinica,
        TratamientoMedicamento.id_tratamiento == plan.id_tratamiento).order_by(TratamientoMedicamento.id_medicamento_plan)).scalars().all()


def _insert_doses(db, values):
    if not values:
        return
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Motor no soportado para generación idempotente de dosis")
    for start in range(0, len(values), 200):
        stmt = insert(TratamientoDosis).values(values[start:start + 200]).on_conflict_do_nothing(
            index_elements=["id_clinica", "id_medicamento_plan", "programada_en_utc"])
        db.execute(stmt)


def _cutoff(db, plan, now=None):
    """Último instante clínicamente vigente; ninguna dosis posterior cuenta."""
    now = as_utc(now or now_utc())
    cierre = db.execute(select(TratamientoEvento.ocurrida_en_utc).where(
        TratamientoEvento.id_clinica == plan.id_clinica,
        TratamientoEvento.id_tratamiento == plan.id_tratamiento,
        TratamientoEvento.accion.in_(["FINALIZAR_TRATAMIENTO", "SUSPENDER_POR_RECETA"])
    ).order_by(TratamientoEvento.id_evento.desc())).scalars().first()
    cutoff = as_utc(cierre)
    if plan.id_receta is not None:
        receta = db.execute(select(Receta.estado, Receta.fecha_anulacion).where(
            Receta.id_clinica == plan.id_clinica, Receta.id_receta == plan.id_receta)).first()
        if not receta or receta.estado != "EMITIDA":
            revoked = as_utc(receta.fecha_anulacion) if receta and receta.fecha_anulacion else now
            cutoff = min(cutoff, revoked) if cutoff else revoked
    return cutoff


def materializar(db, plan, desde, hasta, now=None):
    """Materializa dosis en el rango local respetando períodos suspendidos."""
    now = as_utc(now or now_utc())
    zone = ZoneInfo(plan.zona_horaria)
    cutoff = _cutoff(db, plan, now)
    values = []
    for med in _medicamentos(db, plan):
        events = db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_clinica == plan.id_clinica,
            TratamientoEvento.id_tratamiento == plan.id_tratamiento,
            TratamientoEvento.id_medicamento_plan == med.id_medicamento_plan,
            TratamientoEvento.accion.in_(["SUSPENDER_MEDICAMENTO", "REACTIVAR_MEDICAMENTO", "PRORROGAR_MEDICAMENTO"])
        ).order_by(TratamientoEvento.ocurrida_en_utc, TratamientoEvento.id_evento)).scalars().all()
        day = max(desde, med.fecha_inicio)
        end = min(hasta, med.fecha_fin)
        while day <= end:
            for hour in med.horas_locales:
                instant = _occurrence(day, hour, zone)
                if cutoff is not None and instant > cutoff:
                    continue
                enabled = True
                before_extension = False
                for event in events:
                    stamp = as_utc(event.ocurrida_en_utc)
                    if event.accion == "PRORROGAR_MEDICAMENTO":
                        if day > date.fromisoformat(event.estado_anterior) and instant < stamp:
                            before_extension = True
                    elif stamp < instant:
                        enabled = event.accion == "REACTIVAR_MEDICAMENTO"
                if enabled and not before_extension:
                    values.append(dict(id_clinica=plan.id_clinica, id_medicamento_plan=med.id_medicamento_plan,
                                       programada_en_utc=instant, estado="PENDIENTE"))
                    if len(values) >= 200:
                        _insert_doses(db, values)
                        values.clear()
            if day == end:
                break
            day += timedelta(days=1)
    _insert_doses(db, values)


def puntual(dose):
    if dose.estado != "INGERIDA" or dose.efectiva_en_utc is None:
        return False
    scheduled = as_utc(dose.programada_en_utc)
    return scheduled - timedelta(minutes=30) <= as_utc(dose.efectiva_en_utc) <= scheduled + timedelta(minutes=60)


def _adherencia(db, plan, now=None):
    now = as_utc(now or now_utc())
    local_today = now.astimezone(ZoneInfo(plan.zona_horaria)).date()
    materializar(db, plan, plan.fecha_inicio, min(local_today, plan.fecha_fin), now)
    query = select(TratamientoDosis).join(TratamientoMedicamento,
        TratamientoMedicamento.id_medicamento_plan == TratamientoDosis.id_medicamento_plan).where(
        TratamientoDosis.id_clinica == plan.id_clinica, TratamientoMedicamento.id_clinica == plan.id_clinica,
        TratamientoMedicamento.id_tratamiento == plan.id_tratamiento,
        TratamientoDosis.programada_en_utc <= now, TratamientoDosis.cancelada_en_utc.is_(None))
    cutoff = _cutoff(db, plan, now)
    if cutoff is not None:
        query = query.where(TratamientoDosis.programada_en_utc <= cutoff)
    doses = db.execute(query).scalars().yield_per(500)
    denominator = numerator = 0
    for dose in doses:
        denominator += 1
        numerator += int(puntual(dose))
    value = round(100.0 * numerator / denominator, 1) if denominator else None
    level = "SIN_DATOS" if value is None else "OPTIMA" if value >= 80 else "REGULAR" if value >= 50 else "CRITICA"
    return {"numerador_puntual": numerator, "denominador_programado": denominator,
            "porcentaje": value, "nivel": level, "calculado_en": iso(now)}


def dosis_to_dict(dose, plan, now=None):
    scheduled = as_utc(dose.programada_en_utc)
    now = as_utc(now or now_utc())
    return {"id_dosis": dose.id_dosis, "id_medicamento_plan": dose.id_medicamento_plan,
            "programada_en": iso(scheduled), "programada_hora_local": scheduled.astimezone(ZoneInfo(plan.zona_horaria)).strftime("%H:%M"),
            "zona_horaria": plan.zona_horaria, "estado": dose.estado,
            "vencida": dose.estado == "PENDIENTE" and now > scheduled + timedelta(minutes=60),
            "efectiva_en": iso(dose.efectiva_en_utc), "registrada_en": iso(dose.registrada_en_utc),
            "puntual": puntual(dose), "nota": dose.nota}


def plan_to_dict(db, plan, now=None):
    diag = db.execute(select(Diagnostico.codigo_cie, Diagnostico.descripcion).where(
        Diagnostico.id_diagnostico == plan.id_diagnostico, Diagnostico.id_consulta == plan.id_consulta)).first()
    meds = [{"id_medicamento_plan": m.id_medicamento_plan, "id_receta_detalle": m.id_receta_detalle,
             "medicamento_nombre": m.medicamento_nombre, "dosis": m.dosis, "via_administracion": m.via_administracion,
             "frecuencia_texto_receta": m.frecuencia_texto_receta, "duracion_texto_receta": m.duracion_texto_receta,
             "indicaciones": m.indicaciones, "fecha_inicio": m.fecha_inicio.isoformat(), "fecha_fin": m.fecha_fin.isoformat(),
             "horas_locales": m.horas_locales, "intervalo_horas": intervalo(m.horas_locales), "estado": m.estado}
            for m in _medicamentos(db, plan)]
    return {"id_tratamiento": plan.id_tratamiento, "id_clinica": plan.id_clinica, "id_consulta": plan.id_consulta,
            "id_receta": plan.id_receta, "id_diagnostico": plan.id_diagnostico,
            "diagnostico": {"codigo_cie": diag.codigo_cie, "descripcion": diag.descripcion} if diag else None,
            "id_paciente": plan.id_paciente, "id_medico": plan.id_medico, "fecha_inicio": plan.fecha_inicio.isoformat(),
            "fecha_fin": plan.fecha_fin.isoformat(), "zona_horaria": plan.zona_horaria, "estado": estado_efectivo(db, plan),
            "notas": plan.notas, "motivo_cierre": plan.motivo_cierre, "medicamentos": meds,
            "created_at": iso(plan.created_at), "updated_at": iso(plan.updated_at), "adherencia": _adherencia(db, plan, now)}


def crear_plan(db, user, tenant_id, payload, client_ip=None):
    role, medico_id = authorize(db, user, tenant_id, "treatments:write")
    if role != "MEDICO":
        fail(403, "Solo el médico tratante puede crear planes", "FORBIDDEN")
    consulta = db.execute(select(Consulta).where(Consulta.id_consulta == payload.id_consulta,
        Consulta.id_clinica == tenant_id, Consulta.id_medico == medico_id)).scalar_one_or_none()
    if consulta is None:
        fail(404, "Consulta no encontrada", "NOT_FOUND")
    historia = db.execute(select(HistoriaClinica.id_paciente).where(
        HistoriaClinica.id_historia == consulta.id_historia, HistoriaClinica.id_clinica == tenant_id)).scalar_one_or_none()
    paciente = db.execute(select(Paciente.id_paciente).where(Paciente.id_paciente == historia,
        Paciente.id_clinica == tenant_id)).scalar_one_or_none()
    if paciente is None:
        fail(404, "Paciente no encontrado", "NOT_FOUND")
    diagnosticos = db.execute(select(Diagnostico.id_diagnostico).where(
        Diagnostico.id_consulta == consulta.id_consulta)).scalars().all()
    selected = payload.id_diagnostico
    if selected is None and len(diagnosticos) == 1:
        selected = diagnosticos[0]
    if selected is None or selected not in diagnosticos:
        fail(422, "Seleccione un diagnóstico de la consulta", "VALIDATION")
    detalles = {}
    if payload.id_receta is not None:
        receta = db.execute(select(Receta).where(Receta.id_receta == payload.id_receta,
            Receta.id_clinica == tenant_id, Receta.id_consulta == consulta.id_consulta,
            Receta.id_paciente == paciente, Receta.id_medico == medico_id).with_for_update()).scalar_one_or_none()
        if receta is None:
            fail(404, "Receta no encontrada", "NOT_FOUND")
        if receta.estado != "EMITIDA":
            fail(409, "La receta no está emitida", "CONFLICT")
        rows = db.execute(select(RecetaDetalle).where(RecetaDetalle.id_receta == receta.id_receta)).scalars().all()
        detalles = {d.id_receta_detalle: d for d in rows}
        if set(detalles) != {m.id_receta_detalle for m in payload.medicamentos}:
            fail(422, "Confirme todos los detalles de la receta", "VALIDATION")
    else:
        existing = db.execute(select(Tratamiento.id_tratamiento).where(
            Tratamiento.id_clinica == tenant_id, Tratamiento.id_consulta == consulta.id_consulta,
            Tratamiento.id_receta.is_(None))).scalar_one_or_none()
        if existing is not None:
            fail(409, "Ya existe un plan sin receta para la consulta", "CONFLICT")
    for med in payload.medicamentos:
        validar_pauta(med.fecha_inicio, med.fecha_fin, med.horas_locales, payload.zona_horaria)
    try:
        plan = Tratamiento(id_clinica=tenant_id, id_consulta=consulta.id_consulta, id_receta=payload.id_receta,
            id_diagnostico=selected, id_paciente=paciente, id_medico=medico_id, fecha_inicio=payload.fecha_inicio,
            fecha_fin=payload.fecha_fin, zona_horaria=payload.zona_horaria, estado="ACTIVO", notas=payload.notas)
        db.add(plan)
        db.flush()
        for entry in payload.medicamentos:
            detalle = detalles[entry.id_receta_detalle]
            db.add(TratamientoMedicamento(id_clinica=tenant_id, id_tratamiento=plan.id_tratamiento,
                id_receta_detalle=detalle.id_receta_detalle, medicamento_nombre=detalle.medicamento_nombre,
                dosis=detalle.dosis, via_administracion=detalle.via_administracion,
                frecuencia_texto_receta=detalle.frecuencia, duracion_texto_receta=detalle.duracion,
                indicaciones=entry.indicaciones, fecha_inicio=entry.fecha_inicio, fecha_fin=entry.fecha_fin,
                horas_locales=entry.horas_locales, estado="ACTIVO"))
        db.flush()
        _event(db, plan, user, role, client_ip, "CREAR_TRATAMIENTO", after="ACTIVO")
        now = now_utc()
        local_today = now.astimezone(ZoneInfo(plan.zona_horaria)).date()
        materializar(db, plan, plan.fecha_inicio, min(plan.fecha_fin, local_today + timedelta(days=7)), now)
        result = plan_to_dict(db, plan, now)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        fail(409, "Ya existe un plan para esta receta o consulta", "CONFLICT")
    except Exception:
        db.rollback()
        raise


def listar_planes(db, user, tenant_id, estado=None, id_paciente=None, skip=0, limit=20, client_ip=None):
    role, profile = authorize(db, user, tenant_id, "treatments:read")
    filters = [Tratamiento.id_clinica == tenant_id]
    filters.append(Tratamiento.id_paciente == profile if role == "PACIENTE" else Tratamiento.id_medico == profile)
    if role == "MEDICO" and id_paciente is not None:
        filters.append(Tratamiento.id_paciente == id_paciente)
    query = select(Tratamiento).outerjoin(Receta, and_(Receta.id_receta == Tratamiento.id_receta,
                                                       Receta.id_clinica == Tratamiento.id_clinica)).where(*filters)
    if estado is not None:
        if estado not in ("ACTIVO", "FINALIZADO", "SUSPENDIDO_POR_RECETA"):
            fail(422, "Estado de tratamiento inválido", "VALIDATION")
        invalid_recipe = and_(Tratamiento.id_receta.is_not(None),
                              or_(Receta.estado.is_(None), Receta.estado != "EMITIDA"))
        if estado == "ACTIVO":
            query = query.where(Tratamiento.estado == "ACTIVO", ~invalid_recipe)
        elif estado == "FINALIZADO":
            query = query.where(Tratamiento.estado == estado)
        else:
            query = query.where(or_(Tratamiento.estado == estado,
                                    and_(Tratamiento.estado == "ACTIVO", invalid_recipe)))
    total = db.execute(select(func.count()).select_from(query.order_by(None).subquery())).scalar_one()
    rows = db.execute(query.order_by(Tratamiento.created_at.desc(), Tratamiento.id_tratamiento.desc())
                      .offset(skip).limit(limit)).scalars().all()
    result = {"items": [plan_to_dict(db, row) for row in rows], "total": total}
    _audit_read(db, user, tenant_id, "CONSULTAR_TRATAMIENTOS", client_ip)
    db.commit()
    return result


def obtener_plan(db, user, tenant_id, id_tratamiento, client_ip=None):
    plan = get_owned_plan(db, user, tenant_id, id_tratamiento)
    result = plan_to_dict(db, plan)
    _audit_read(db, user, tenant_id, "CONSULTAR_TRATAMIENTO", client_ip, plan.id_tratamiento)
    db.commit()
    return result


def cronograma(db, user, tenant_id, id_tratamiento, fecha, client_ip=None):
    plan = get_owned_plan(db, user, tenant_id, id_tratamiento)
    materializar(db, plan, fecha, fecha)
    zone = ZoneInfo(plan.zona_horaria)
    start = datetime.combine(fecha, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(fecha + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
    query = select(TratamientoDosis).join(TratamientoMedicamento,
        TratamientoMedicamento.id_medicamento_plan == TratamientoDosis.id_medicamento_plan).where(
        TratamientoDosis.id_clinica == tenant_id, TratamientoMedicamento.id_clinica == tenant_id,
        TratamientoMedicamento.id_tratamiento == plan.id_tratamiento, TratamientoDosis.cancelada_en_utc.is_(None),
        TratamientoDosis.programada_en_utc >= start, TratamientoDosis.programada_en_utc < end)
    cutoff = _cutoff(db, plan)
    if cutoff is not None:
        query = query.where(TratamientoDosis.programada_en_utc <= cutoff)
    rows = db.execute(query.order_by(TratamientoDosis.programada_en_utc, TratamientoDosis.id_dosis)).scalars().all()
    result = {"id_tratamiento": plan.id_tratamiento, "fecha": fecha.isoformat(), "zona_horaria": plan.zona_horaria,
              "dosis": [dosis_to_dict(d, plan) for d in rows], "adherencia": _adherencia(db, plan)}
    _audit_read(db, user, tenant_id, "CONSULTAR_CRONOGRAMA", client_ip, plan.id_tratamiento)
    db.commit()
    return result


def adherencia_plan(db, user, tenant_id, id_tratamiento, client_ip=None):
    plan = get_owned_plan(db, user, tenant_id, id_tratamiento)
    result = _adherencia(db, plan)
    _audit_read(db, user, tenant_id, "CONSULTAR_ADHERENCIA", client_ip, plan.id_tratamiento)
    db.commit()
    return result


def _operacion_to_response(op: TratamientoOperacionDosis, id_dosis: int, idempotency_key: str):
    gen = op.generacion if op.generacion is not None else 1
    if op.estado == "CONFIRMADA":
        return {
            "confirmado": True,
            "en_curso": False,
            "rechazado": False,
            "estado": "CONFIRMADA",
            "id_dosis": id_dosis,
            "idempotency_key": idempotency_key,
            "dosis": op.respuesta_json,
            "mensaje": None,
            "generacion": gen,
        }
    elif op.estado == "EN_CURSO":
        return {
            "confirmado": False,
            "en_curso": True,
            "rechazado": False,
            "estado": "EN_CURSO",
            "id_dosis": id_dosis,
            "idempotency_key": idempotency_key,
            "dosis": None,
            "mensaje": "Operación en curso o de resultado incierto",
            "generacion": gen,
        }
    else:  # RECHAZADA
        return {
            "confirmado": False,
            "en_curso": False,
            "rechazado": True,
            "estado": "RECHAZADA",
            "id_dosis": id_dosis,
            "idempotency_key": idempotency_key,
            "dosis": None,
            "mensaje": op.error_detail,
            "generacion": gen,
        }


def iniciar_intento_dosis(db: Session, user: Usuario, tenant_id: int, id_dosis: int, idempotency_key: str, request_hash: str, client_ip=None):
    # 1. Valida paciente titular, clínica, plan activo y dosis existente y no cancelada
    role, patient_id = authorize(db, user, tenant_id, "treatments:dose:record")
    if role != "PACIENTE":
        fail(403, "Solo el paciente titular puede registrar tomas", "FORBIDDEN")

    key = (idempotency_key or "").strip()
    if not 1 <= len(key) <= 128:
        fail(422, "Idempotency-Key debe tener entre 1 y 128 caracteres", "VALIDATION")
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    req_hash = (request_hash or "").strip()
    if not req_hash:
        fail(422, "request_hash es requerido", "VALIDATION")

    # CU16 bloquea primero la receta y luego el plan. Mantener ese orden evita
    # un interbloqueo si se anula la receta mientras el paciente inicia una toma.
    query = select(TratamientoDosis, TratamientoMedicamento, Tratamiento).join(
        TratamientoMedicamento, TratamientoMedicamento.id_medicamento_plan == TratamientoDosis.id_medicamento_plan
    ).join(Tratamiento, Tratamiento.id_tratamiento == TratamientoMedicamento.id_tratamiento).where(
        TratamientoDosis.id_dosis == id_dosis, TratamientoDosis.id_clinica == tenant_id,
        TratamientoMedicamento.id_clinica == tenant_id, Tratamiento.id_clinica == tenant_id,
        Tratamiento.id_paciente == patient_id
    )
    row = db.execute(query).first()
    if row is None:
        fail(404, "Dosis no encontrada", "NOT_FOUND")
    dose, med, plan = row

    vigente = receta_vigente(db, plan, lock=True)
    row = db.execute(query.with_for_update().execution_options(populate_existing=True)).first()
    if row is None:
        fail(404, "Dosis no encontrada", "NOT_FOUND")
    dose, med, plan = row
    if not vigente or plan.estado != "ACTIVO":
        fail(409, "El tratamiento no está activo", "CONFLICT")

    if dose.cancelada_en_utc is not None:
        fail(409, "La dosis fue cancelada", "CONFLICT")

    # Busca operación previa para esta clave
    prior_op = db.execute(select(TratamientoOperacionDosis).where(
        TratamientoOperacionDosis.id_clinica == tenant_id,
        TratamientoOperacionDosis.id_usuario == user.id_usuario,
        TratamientoOperacionDosis.id_dosis == id_dosis,
        TratamientoOperacionDosis.idempotencia_hash == key_hash
    )).scalar_one_or_none()

    if prior_op is None:
        prior_ev = db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_clinica == tenant_id,
            TratamientoEvento.id_usuario == user.id_usuario,
            TratamientoEvento.id_dosis == id_dosis,
            TratamientoEvento.idempotencia_hash == key_hash,
            TratamientoEvento.accion == "REGISTRAR_DOSIS"
        )).scalar_one_or_none()
        if prior_ev:
            if prior_ev.request_hash != req_hash:
                fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
            db.commit()
            return {
                "confirmado": True,
                "en_curso": False,
                "rechazado": False,
                "estado": "CONFIRMADA",
                "id_dosis": id_dosis,
                "idempotency_key": idempotency_key,
                "dosis": prior_ev.respuesta_json,
                "mensaje": None,
                "generacion": dose.generacion or 1,
            }

    # 3. Una clave nueva puede corregir una dosis ya registrada; su evento anterior
    # permanece intacto. La generación solo invalida intentos antiguos.
    # Si ya existe operación previa para (tenant_id, user.id_usuario, id_dosis, key_hash):
    #    - Si tiene request_hash diferente: fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT").
    #    - Devuelve el estado de la operación existente.
    if prior_op is not None:
        if prior_op.request_hash != req_hash:
            fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
        db.commit()
        return _operacion_to_response(prior_op, id_dosis, idempotency_key)

    # 5. Si existe OTRA operación en curso (EN_CURSO) para la misma dosis: fail(409, "Existe una operación en curso o de resultado incierto para esta dosis", "OPERATION_IN_PROGRESS")
    other_active = db.execute(select(TratamientoOperacionDosis).where(
        TratamientoOperacionDosis.id_clinica == tenant_id,
        TratamientoOperacionDosis.id_dosis == id_dosis,
        TratamientoOperacionDosis.estado == "EN_CURSO"
    )).first()
    if other_active:
        fail(409, "Existe una operación en curso o de resultado incierto para esta dosis", "OPERATION_IN_PROGRESS")

    # 6. Inserta TratamientoOperacionDosis con estado="EN_CURSO", generacion=dose.generacion, request_hash=request_hash, idempotencia_hash=key_hash.
    # 7. Hace commit y devuelve respuesta con estado EN_CURSO, generacion=dose.generacion.
    gen = dose.generacion or 1
    try:
        nueva_op = TratamientoOperacionDosis(
            id_clinica=tenant_id,
            id_tratamiento=plan.id_tratamiento,
            id_dosis=id_dosis,
            id_usuario=user.id_usuario,
            idempotencia_hash=key_hash,
            request_hash=req_hash,
            generacion=gen,
            estado="EN_CURSO",
        )
        db.add(nueva_op)
        db.commit()
    except IntegrityError:
        db.rollback()
        prior_race = db.execute(select(TratamientoOperacionDosis).where(
            TratamientoOperacionDosis.id_clinica == tenant_id,
            TratamientoOperacionDosis.id_usuario == user.id_usuario,
            TratamientoOperacionDosis.id_dosis == id_dosis,
            TratamientoOperacionDosis.idempotencia_hash == key_hash
        )).scalar_one_or_none()
        if prior_race:
            if prior_race.request_hash != req_hash:
                fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
            return _operacion_to_response(prior_race, id_dosis, idempotency_key)
        fail(409, "Existe una operación en curso o de resultado incierto para esta dosis", "OPERATION_IN_PROGRESS")

    return {
        "confirmado": False,
        "en_curso": True,
        "rechazado": False,
        "estado": "EN_CURSO",
        "id_dosis": id_dosis,
        "idempotency_key": idempotency_key,
        "dosis": None,
        "mensaje": "Operación en curso",
        "generacion": gen,
    }


def registrar_dosis(db, user, tenant_id, id_dosis, payload, idempotency_key, client_ip=None):
    # 1. Autenticación, rol PACIENTE, titularidad del plan, tenant y dosis.
    role, patient_id = authorize(db, user, tenant_id, "treatments:dose:record")
    if role != "PACIENTE":
        fail(403, "Solo el paciente titular puede registrar tomas", "FORBIDDEN")

    # 2. Validación de clave (1-128 chars). Hashes key_hash y request_hash.
    key = (idempotency_key or "").strip()
    if not 1 <= len(key) <= 128:
        fail(422, "Idempotency-Key debe tener entre 1 y 128 caracteres", "VALIDATION")
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    serialized = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    request_hash = hashlib.sha256(serialized.encode()).hexdigest()

    query = select(TratamientoDosis, TratamientoMedicamento, Tratamiento).join(
        TratamientoMedicamento, TratamientoMedicamento.id_medicamento_plan == TratamientoDosis.id_medicamento_plan
    ).join(Tratamiento, Tratamiento.id_tratamiento == TratamientoMedicamento.id_tratamiento).where(
        TratamientoDosis.id_dosis == id_dosis, TratamientoDosis.id_clinica == tenant_id,
        TratamientoMedicamento.id_clinica == tenant_id, Tratamiento.id_clinica == tenant_id,
        Tratamiento.id_paciente == patient_id)
    row = db.execute(query).first()
    if row is None:
        fail(404, "Dosis no encontrada", "NOT_FOUND")
    dose, med, plan = row

    # 3. Busca operación previa para la misma clave (tenant_id, user.id_usuario, id_dosis, key_hash):
    prior_op = db.execute(select(TratamientoOperacionDosis).where(
        TratamientoOperacionDosis.id_clinica == tenant_id,
        TratamientoOperacionDosis.id_usuario == user.id_usuario,
        TratamientoOperacionDosis.id_dosis == id_dosis,
        TratamientoOperacionDosis.idempotencia_hash == key_hash
    )).scalar_one_or_none()

    if prior_op is None:
        prior_event = db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_clinica == tenant_id,
            TratamientoEvento.id_usuario == user.id_usuario,
            TratamientoEvento.id_dosis == id_dosis,
            TratamientoEvento.idempotencia_hash == key_hash,
            TratamientoEvento.accion == "REGISTRAR_DOSIS"
        )).scalar_one_or_none()
        if prior_event:
            if prior_event.request_hash != request_hash:
                fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
            return prior_event.respuesta_json

    operacion = None
    if prior_op:
        if prior_op.estado == "CONFIRMADA":
            if prior_op.request_hash != request_hash:
                fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
            return prior_op.respuesta_json
        elif prior_op.estado == "EN_CURSO":
            if prior_op.request_hash != request_hash:
                fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
            operacion = prior_op
        elif prior_op.estado == "RECHAZADA":
            if prior_op.request_hash != request_hash:
                fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
            fail(409, "La operación asociada a esta clave de idempotencia fue rechazada previamente. Debe utilizar una nueva clave.", "OPERATION_REJECTED")

    # 4. Si no es la misma clave: verificar si existe OTRA operación en curso (EN_CURSO) para esta dosis (tenant_id, id_dosis):
    if operacion is None:
        other_active = db.execute(select(TratamientoOperacionDosis).where(
            TratamientoOperacionDosis.id_clinica == tenant_id,
            TratamientoOperacionDosis.id_dosis == id_dosis,
            TratamientoOperacionDosis.estado == "EN_CURSO"
        )).first()
        if other_active:
            fail(409, "Existe una operación en curso o de resultado incierto para esta dosis. Debe resolver o recuperar la operación previa.", "OPERATION_IN_PROGRESS")

    # 5. Registro / inicio de la operación:
    now = now_utc()
    try:
        if operacion is None:
            operacion = TratamientoOperacionDosis(
                id_clinica=tenant_id,
                id_tratamiento=plan.id_tratamiento,
                id_dosis=id_dosis,
                id_usuario=user.id_usuario,
                idempotencia_hash=key_hash,
                request_hash=request_hash,
                generacion=dose.generacion or 1,
                estado="EN_CURSO",
            )
            db.add(operacion)
            db.commit()
    except IntegrityError:
        db.rollback()
        prior_race = db.execute(select(TratamientoOperacionDosis).where(
            TratamientoOperacionDosis.id_clinica == tenant_id,
            TratamientoOperacionDosis.id_usuario == user.id_usuario,
            TratamientoOperacionDosis.id_dosis == id_dosis,
            TratamientoOperacionDosis.idempotencia_hash == key_hash
        )).scalar_one_or_none()
        if prior_race and prior_race.estado == "CONFIRMADA":
            if prior_race.request_hash == request_hash:
                return prior_race.respuesta_json
            fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
        prior_ev = db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_clinica == tenant_id,
            TratamientoEvento.id_usuario == user.id_usuario,
            TratamientoEvento.id_dosis == id_dosis,
            TratamientoEvento.idempotencia_hash == key_hash
        )).scalar_one_or_none()
        if prior_ev:
            if prior_ev.request_hash == request_hash:
                return prior_ev.respuesta_json
            fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")
        fail(409, "Existe una operación en curso o de resultado incierto para esta dosis. Debe resolver o recuperar la operación previa.", "OPERATION_IN_PROGRESS")

    operacion_id = operacion.id_operacion

    def _rechazar(status_code, message, code):
        db.rollback()
        try:
            db.execute(update(TratamientoOperacionDosis).where(
                TratamientoOperacionDosis.id_operacion == operacion_id,
                TratamientoOperacionDosis.estado != "CONFIRMADA"
            ).values(estado="RECHAZADA", error_detail=message, updated_at=now_utc()))
            db.commit()
        except Exception:
            db.rollback()
        fail(status_code, message, code)

    # 6. Validación clínica y de vigencia de receta / plan con fencing:
    vigente = receta_vigente(db, plan, lock=True)
    row = db.execute(query.with_for_update().execution_options(populate_existing=True)).first()
    if row is None:
        fail(404, "Dosis no encontrada", "NOT_FOUND")
    dose, med, plan = row

    db.refresh(operacion)
    if operacion.estado == "CONFIRMADA":
        if operacion.request_hash == request_hash:
            return operacion.respuesta_json
        fail(409, "Clave de idempotencia reutilizada con otros datos", "IDEMPOTENCY_CONFLICT")

    if (dose.generacion or 1) != (operacion.generacion or 1):
        _rechazar(409, "Operación desactualizada por cambio de generación o resolución previa", "CONFLICT")

    if not vigente or plan.estado != "ACTIVO":
        _rechazar(409, "El tratamiento no está activo", "CONFLICT")

    if dose.cancelada_en_utc is not None:
        _rechazar(409, "La dosis fue cancelada", "CONFLICT")

    scheduled = as_utc(dose.programada_en_utc)
    effective = as_utc(payload.efectiva_en)
    if payload.estado == "OMITIDA" and now < scheduled:
        _rechazar(422, "No se puede omitir una dosis futura", "VALIDATION")

    plan_start = datetime.combine(plan.fecha_inicio, time.min, tzinfo=ZoneInfo(plan.zona_horaria)).astimezone(timezone.utc)
    if effective is not None and (effective > now or effective < plan_start):
        _rechazar(422, "La hora efectiva está fuera del período permitido", "VALIDATION")

    # 7. Ejecución y confirmación:
    try:
        before = dose.estado
        dose.estado = payload.estado
        dose.efectiva_en_utc = effective
        dose.registrada_en_utc = now
        dose.nota = payload.nota
        dose.generacion = (dose.generacion or 1) + 1

        following = db.execute(select(TratamientoDosis.id_dosis).where(
            TratamientoDosis.id_clinica == tenant_id,
            TratamientoDosis.id_medicamento_plan == med.id_medicamento_plan,
            TratamientoDosis.programada_en_utc > dose.programada_en_utc
        ).order_by(TratamientoDosis.programada_en_utc, TratamientoDosis.id_dosis).limit(2)).scalars().all()
        db.execute(update(TratamientoDosis).where(TratamientoDosis.id_clinica == tenant_id,
            TratamientoDosis.id_dosis.in_([dose.id_dosis, *following])
        ).values(alertas_evaluadas_en_utc=None))
        db.flush()

        result = dosis_to_dict(dose, plan, now)

        _event(db, plan, user, role, client_ip, "REGISTRAR_DOSIS", dose=dose, med=med,
               before=before, after=payload.estado, note=payload.nota, effective=effective,
               key_hash=key_hash, request_hash=request_hash, response=result)

        db.execute(update(TratamientoOperacionDosis).where(
            TratamientoOperacionDosis.id_operacion == operacion_id
        ).values(estado="CONFIRMADA", generacion=dose.generacion, respuesta_json=result, updated_at=now))

        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        prior = db.execute(select(TratamientoOperacionDosis).where(
            TratamientoOperacionDosis.id_clinica == tenant_id,
            TratamientoOperacionDosis.id_usuario == user.id_usuario,
            TratamientoOperacionDosis.id_dosis == id_dosis,
            TratamientoOperacionDosis.idempotencia_hash == key_hash
        )).scalar_one_or_none()
        if prior and prior.estado == "CONFIRMADA":
            if prior.request_hash == request_hash:
                return prior.respuesta_json
            fail(409, "Conflicto al registrar la dosis", "IDEMPOTENCY_CONFLICT")
        prior_ev = db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_clinica == tenant_id,
            TratamientoEvento.id_usuario == user.id_usuario,
            TratamientoEvento.id_dosis == id_dosis,
            TratamientoEvento.idempotencia_hash == key_hash
        )).scalar_one_or_none()
        if prior_ev:
            if prior_ev.request_hash == request_hash:
                try:
                    db.execute(update(TratamientoOperacionDosis).where(
                        TratamientoOperacionDosis.id_operacion == operacion_id
                    ).values(estado="CONFIRMADA", generacion=dose.generacion, respuesta_json=prior_ev.respuesta_json, updated_at=now_utc()))
                    db.commit()
                except Exception:
                    db.rollback()
                return prior_ev.respuesta_json
            fail(409, "Conflicto al registrar la dosis", "IDEMPOTENCY_CONFLICT")
        try:
            db.execute(update(TratamientoOperacionDosis).where(
                TratamientoOperacionDosis.id_operacion == operacion_id,
                TratamientoOperacionDosis.estado == "EN_CURSO"
            ).values(estado="RECHAZADA", error_detail="Conflicto al registrar la dosis", updated_at=now_utc()))
            db.commit()
        except Exception:
            db.rollback()
        fail(409, "Conflicto al registrar la dosis", "IDEMPOTENCY_CONFLICT")
    except TreatmentError:
        raise
    except Exception:
        db.rollback()
        raise


def consultar_idempotencia_dosis(db, user, tenant_id, id_dosis, idempotency_key, client_ip=None):
    role, patient_id = authorize(db, user, tenant_id, "treatments:dose:record")
    if role != "PACIENTE":
        fail(403, "Solo el paciente titular puede registrar tomas", "FORBIDDEN")
    query = select(TratamientoDosis).join(
        TratamientoMedicamento, TratamientoMedicamento.id_medicamento_plan == TratamientoDosis.id_medicamento_plan
    ).join(Tratamiento, Tratamiento.id_tratamiento == TratamientoMedicamento.id_tratamiento).where(
        TratamientoDosis.id_dosis == id_dosis,
        TratamientoDosis.id_clinica == tenant_id,
        TratamientoMedicamento.id_clinica == tenant_id,
        Tratamiento.id_clinica == tenant_id,
        Tratamiento.id_paciente == patient_id
    )
    dose = db.execute(query).scalar_one_or_none()
    if dose is None:
        fail(404, "Dosis no encontrada", "NOT_FOUND")
    key = (idempotency_key or "").strip()
    if not 1 <= len(key) <= 128:
        fail(422, "Idempotency-Key debe tener entre 1 y 128 caracteres", "VALIDATION")
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    prior_op = db.execute(select(TratamientoOperacionDosis).where(
        TratamientoOperacionDosis.id_clinica == tenant_id,
        TratamientoOperacionDosis.id_usuario == user.id_usuario,
        TratamientoOperacionDosis.id_dosis == id_dosis,
        TratamientoOperacionDosis.idempotencia_hash == key_hash
    )).scalar_one_or_none()

    if prior_op is None:
        prior_ev = db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_clinica == tenant_id,
            TratamientoEvento.id_usuario == user.id_usuario,
            TratamientoEvento.id_dosis == id_dosis,
            TratamientoEvento.idempotencia_hash == key_hash,
            TratamientoEvento.accion == "REGISTRAR_DOSIS"
        )).scalar_one_or_none()
        if prior_ev:
            db.commit()
            return {
                "confirmado": True,
                "en_curso": False,
                "rechazado": False,
                "estado": "CONFIRMADA",
                "id_dosis": id_dosis,
                "idempotency_key": idempotency_key,
                "dosis": prior_ev.respuesta_json,
                "mensaje": None,
                "generacion": dose.generacion or 1,
            }

    if prior_op is not None:
        db.commit()
        return _operacion_to_response(prior_op, id_dosis, idempotency_key)

    other_en_curso = db.execute(select(TratamientoOperacionDosis).where(
        TratamientoOperacionDosis.id_clinica == tenant_id,
        TratamientoOperacionDosis.id_dosis == id_dosis,
        TratamientoOperacionDosis.estado == "EN_CURSO"
    )).first()

    db.commit()
    if other_en_curso:
        return {
            "confirmado": False,
            "en_curso": True,
            "rechazado": False,
            "estado": "EN_CURSO",
            "id_dosis": id_dosis,
            "idempotency_key": idempotency_key,
            "dosis": None,
            "mensaje": "Existe otra operación en curso sobre esta dosis",
            "generacion": dose.generacion or 1,
        }
    return {
        "confirmado": False,
        "en_curso": False,
        "rechazado": False,
        "estado": "NO_INICIADA",
        "id_dosis": id_dosis,
        "idempotency_key": idempotency_key,
        "dosis": None,
        "mensaje": None,
        "generacion": dose.generacion or 1,
    }


def resolver_operacion_abandonada(db: Session, user: Usuario, tenant_id: int, id_dosis: int, idempotency_key: str, client_ip=None, _retry_conflict=True):
    # 1. Valida titularidad del paciente sobre la dosis
    role, patient_id = authorize(db, user, tenant_id, "treatments:dose:record")
    if role != "PACIENTE":
        fail(403, "Solo el paciente titular puede registrar tomas", "FORBIDDEN")

    key = (idempotency_key or "").strip()
    if not 1 <= len(key) <= 128:
        fail(422, "Idempotency-Key debe tener entre 1 y 128 caracteres", "VALIDATION")
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    # 2. Adquiere bloqueo with_for_update() en TratamientoDosis y en TratamientoOperacionDosis
    query_dose = select(TratamientoDosis).join(
        TratamientoMedicamento, TratamientoMedicamento.id_medicamento_plan == TratamientoDosis.id_medicamento_plan
    ).join(
        Tratamiento, Tratamiento.id_tratamiento == TratamientoMedicamento.id_tratamiento
    ).where(
        TratamientoDosis.id_dosis == id_dosis,
        TratamientoDosis.id_clinica == tenant_id,
        TratamientoMedicamento.id_clinica == tenant_id,
        Tratamiento.id_clinica == tenant_id,
        Tratamiento.id_paciente == patient_id
    ).with_for_update().execution_options(populate_existing=True)

    dose = db.execute(query_dose).scalar_one_or_none()
    if dose is None:
        fail(404, "Dosis no encontrada", "NOT_FOUND")

    query_op = select(TratamientoOperacionDosis).where(
        TratamientoOperacionDosis.id_clinica == tenant_id,
        TratamientoOperacionDosis.id_usuario == user.id_usuario,
        TratamientoOperacionDosis.id_dosis == id_dosis,
        TratamientoOperacionDosis.idempotencia_hash == key_hash
    ).with_for_update().execution_options(populate_existing=True)

    op = db.execute(query_op).scalar_one_or_none()
    if op is None:
        prior_ev = db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_clinica == tenant_id,
            TratamientoEvento.id_usuario == user.id_usuario,
            TratamientoEvento.id_dosis == id_dosis,
            TratamientoEvento.idempotencia_hash == key_hash,
            TratamientoEvento.accion == "REGISTRAR_DOSIS"
        )).scalar_one_or_none()
        if prior_ev:
            db.commit()
            return {
                "confirmado": True,
                "en_curso": False,
                "rechazado": False,
                "estado": "CONFIRMADA",
                "id_dosis": id_dosis,
                "idempotency_key": idempotency_key,
                "dosis": prior_ev.respuesta_json,
                "mensaje": None,
                "generacion": dose.generacion or 1,
            }
        # El marcador local se guardó antes de enviar la intención. Si la red
        # perdió esa petición, una respuesta 404 dejaría al paciente bloqueado
        # para siempre tras el logout. Reservar la clave como rechazada impide
        # que una intención o un registro clínico tardío la reutilicen.
        plan_id = db.execute(select(TratamientoMedicamento.id_tratamiento).where(
            TratamientoMedicamento.id_clinica == tenant_id,
            TratamientoMedicamento.id_medicamento_plan == dose.id_medicamento_plan,
        )).scalar_one()
        op = TratamientoOperacionDosis(
            id_clinica=tenant_id,
            id_tratamiento=plan_id,
            id_dosis=id_dosis,
            id_usuario=user.id_usuario,
            idempotencia_hash=key_hash,
            request_hash="0" * 64,
            generacion=dose.generacion or 1,
            estado="RECHAZADA",
            error_detail="Operación resuelta antes de iniciar",
        )
        db.add(op)
        try:
            db.commit()
        except IntegrityError:
            # Un registro directo pudo crear la misma clave después de la
            # consulta anterior. Releer su estado en una transacción nueva.
            db.rollback()
            if not _retry_conflict:
                raise
            return resolver_operacion_abandonada(
                db, user, tenant_id, id_dosis, idempotency_key, client_ip,
                _retry_conflict=False,
            )
        return _operacion_to_response(op, id_dosis, idempotency_key)

    # 3. Si la operación está en CONFIRMADA: devuelve la dosis confirmada
    if op.estado == "CONFIRMADA":
        db.commit()
        return _operacion_to_response(op, id_dosis, idempotency_key)

    # 4. Si está en RECHAZADA: devuelve su estado de rechazo
    if op.estado == "RECHAZADA":
        db.commit()
        return _operacion_to_response(op, id_dosis, idempotency_key)

    # 5. Si está en EN_CURSO:
    #    - Incrementa dose.generacion += 1 (fencing efectivo para cualquier trabajador previo colgado)
    #    - Actualiza TratamientoOperacionDosis: estado = "RECHAZADA", error_detail = "Operación resuelta por abandono", updated_at = now_utc()
    #    - Hace commit y devuelve estado RECHAZADA.
    now = now_utc()
    dose.generacion = (dose.generacion or 1) + 1
    op.estado = "RECHAZADA"
    op.error_detail = "Operación resuelta por abandono"
    op.updated_at = now
    db.commit()

    return _operacion_to_response(op, id_dosis, idempotency_key)


def _doctor_plan(db, user, tenant_id, id_tratamiento):
    role, _ = authorize(db, user, tenant_id, "treatments:write")
    if role != "MEDICO":
        fail(403, "Solo el médico tratante puede ajustar el plan", "FORBIDDEN")
    plan = get_owned_plan(db, user, tenant_id, id_tratamiento, "treatments:write")
    _active(db, plan)
    plan = get_owned_plan(db, user, tenant_id, id_tratamiento, "treatments:write", for_update=True)
    _active(db, plan)
    return role, plan


def evolucion(db, user, tenant_id, id_tratamiento, payload, client_ip=None):
    role, plan = _doctor_plan(db, user, tenant_id, id_tratamiento)
    try:
        previous_note = plan.notas
        plan.notas = payload.nota
        event = _event(db, plan, user, role, client_ip, "EVOLUCION_TRATAMIENTO", note=payload.nota)
        registrar_auditoria(db, id_usuario=user.id_usuario, id_clinica=tenant_id,
            tabla_afectada="tratamientos", registro_id=plan.id_tratamiento, accion="UPDATE",
            descripcion="Actualizar evolución clínica", datos_anteriores={"notas": previous_note},
            datos_nuevos={"notas": payload.nota}, direccion_ip=client_ip)
        db.flush()
        result = {"id_evento": event.id_evento, "id_tratamiento": plan.id_tratamiento,
                  "accion": event.accion, "nota": event.nota, "ocurrida_en": iso(event.ocurrida_en_utc)}
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def cambiar_medicamento(db, user, tenant_id, id_tratamiento, id_medicamento_plan, accion, payload, client_ip=None):
    role, plan = _doctor_plan(db, user, tenant_id, id_tratamiento)
    med = db.execute(select(TratamientoMedicamento).where(
        TratamientoMedicamento.id_clinica == tenant_id, TratamientoMedicamento.id_tratamiento == id_tratamiento,
        TratamientoMedicamento.id_medicamento_plan == id_medicamento_plan).with_for_update()).scalar_one_or_none()
    if med is None:
        fail(404, "Medicamento del plan no encontrado", "NOT_FOUND")
    action = accion.lower()
    if action not in ("suspender", "reactivar"):
        fail(422, "Acción inválida", "VALIDATION")
    target = "SUSPENDIDO" if action == "suspender" else "ACTIVO"
    if med.estado == target:
        fail(409, "El medicamento ya está en ese estado", "CONFLICT")
    now = now_utc()
    try:
        # Materializar la historia antes de cambiar el estado para no perder tomas.
        today = now.astimezone(ZoneInfo(plan.zona_horaria)).date()
        materializar(db, plan, plan.fecha_inicio, min(today, plan.fecha_fin), now)
        before = med.estado
        med.estado = target
        med.suspendido_desde = now if target == "SUSPENDIDO" else None
        if target == "SUSPENDIDO":
            db.execute(update(TratamientoDosis).where(TratamientoDosis.id_clinica == tenant_id,
                TratamientoDosis.id_medicamento_plan == med.id_medicamento_plan,
                TratamientoDosis.programada_en_utc > now, TratamientoDosis.cancelada_en_utc.is_(None)
            ).values(cancelada_en_utc=now))
        else:
            db.execute(update(TratamientoDosis).where(TratamientoDosis.id_clinica == tenant_id,
                TratamientoDosis.id_medicamento_plan == med.id_medicamento_plan,
                TratamientoDosis.programada_en_utc > now, TratamientoDosis.cancelada_en_utc.is_not(None)
            ).values(cancelada_en_utc=None))
        _event(db, plan, user, role, client_ip, "SUSPENDER_MEDICAMENTO" if target == "SUSPENDIDO" else "REACTIVAR_MEDICAMENTO",
               med=med, before=before, after=target, note=payload.motivo)
        if target == "ACTIVO":
            materializar(db, plan, today, min(plan.fecha_fin, today + timedelta(days=7)), now)
        result = plan_to_dict(db, plan, now)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def prorrogar(db, user, tenant_id, id_tratamiento, payload, client_ip=None):
    role, plan = _doctor_plan(db, user, tenant_id, id_tratamiento)
    if payload.fecha_fin <= plan.fecha_fin:
        fail(409, "La nueva fecha debe ser posterior a la fecha vigente", "CONFLICT")
    meds = {m.id_medicamento_plan: m for m in _medicamentos(db, plan)}
    for entry in payload.medicamentos:
        med = meds.get(entry.id_medicamento_plan)
        if med is None:
            fail(404, "Medicamento del plan no encontrado", "NOT_FOUND")
        if med.estado != "ACTIVO" or entry.fecha_fin <= med.fecha_fin or entry.fecha_fin > payload.fecha_fin or (entry.fecha_fin - med.fecha_fin).days > 366:
            fail(422, "Prórroga de medicamento inválida", "VALIDATION")
        validar_pauta(med.fecha_fin + timedelta(days=1), entry.fecha_fin, med.horas_locales, plan.zona_horaria)
    now = now_utc()
    try:
        previous = plan.fecha_fin
        plan.fecha_fin = payload.fecha_fin
        _event(db, plan, user, role, client_ip, "PRORROGAR_TRATAMIENTO",
               before=previous.isoformat(), after=payload.fecha_fin.isoformat(), note=payload.motivo)
        for entry in payload.medicamentos:
            med = meds[entry.id_medicamento_plan]
            old = med.fecha_fin
            med.fecha_fin = entry.fecha_fin
            _event(db, plan, user, role, client_ip, "PRORROGAR_MEDICAMENTO", med=med,
                   before=old.isoformat(), after=entry.fecha_fin.isoformat(), note=payload.motivo)
        today = now.astimezone(ZoneInfo(plan.zona_horaria)).date()
        materializar(db, plan, today, min(plan.fecha_fin, today + timedelta(days=7)), now)
        result = plan_to_dict(db, plan, now)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def finalizar(db, user, tenant_id, id_tratamiento, payload, client_ip=None):
    role, plan = _doctor_plan(db, user, tenant_id, id_tratamiento)
    now = now_utc()
    try:
        today = now.astimezone(ZoneInfo(plan.zona_horaria)).date()
        materializar(db, plan, plan.fecha_inicio, min(today, plan.fecha_fin), now)
        med_ids = select(TratamientoMedicamento.id_medicamento_plan).where(
            TratamientoMedicamento.id_clinica == tenant_id, TratamientoMedicamento.id_tratamiento == id_tratamiento)
        db.execute(update(TratamientoDosis).where(TratamientoDosis.id_clinica == tenant_id,
            TratamientoDosis.id_medicamento_plan.in_(med_ids), TratamientoDosis.programada_en_utc > now,
            TratamientoDosis.cancelada_en_utc.is_(None)).values(cancelada_en_utc=now))
        plan.estado = "FINALIZADO"
        plan.motivo_cierre = payload.motivo
        _event(db, plan, user, role, client_ip, "FINALIZAR_TRATAMIENTO", before="ACTIVO", after="FINALIZADO", note=payload.motivo)
        result = plan_to_dict(db, plan, now)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def reconciliar_anulacion(db, receta, user, client_ip=None):
    """Suspende CU17 dentro de la transacción que anula una receta CU16."""
    plan = db.execute(select(Tratamiento).where(Tratamiento.id_clinica == receta.id_clinica,
        Tratamiento.id_receta == receta.id_receta).with_for_update()).scalar_one_or_none()
    if plan is None or plan.estado != "ACTIVO":
        return
    now = as_utc(receta.fecha_anulacion or now_utc())
    today = now.astimezone(ZoneInfo(plan.zona_horaria)).date()
    materializar(db, plan, plan.fecha_inicio, min(today, plan.fecha_fin), now)
    med_ids = select(TratamientoMedicamento.id_medicamento_plan).where(
        TratamientoMedicamento.id_clinica == plan.id_clinica,
        TratamientoMedicamento.id_tratamiento == plan.id_tratamiento)
    db.execute(update(TratamientoDosis).where(TratamientoDosis.id_clinica == plan.id_clinica,
        TratamientoDosis.id_medicamento_plan.in_(med_ids), TratamientoDosis.programada_en_utc > now,
        TratamientoDosis.cancelada_en_utc.is_(None)).values(cancelada_en_utc=now))
    role = db.execute(select(Rol.nombre).where(Rol.id_rol == user.id_rol)).scalar_one_or_none()
    plan.estado = "SUSPENDIDO_POR_RECETA"
    _event(db, plan, user, (role or "DESCONOCIDO").upper(), client_ip, "SUSPENDER_POR_RECETA",
           before="ACTIVO", after="SUSPENDIDO_POR_RECETA", note=receta.motivo_anulacion)
