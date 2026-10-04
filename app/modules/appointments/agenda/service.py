"""Reglas CU05 sobre sesiones síncronas y tablas existentes.

Las citas se consultan sin filtrar estados: su catálogo aún no está definido.
No se registran modelos ni se ejecuta DDL para citas. Los intervalos son [inicio, fin).
"""
from datetime import date, datetime, time, timedelta, timezone
import unicodedata

from fastapi import HTTPException
from sqlalchemy import BigInteger, Date, Time, column, func, inspect, select, table
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.appointments.doctor_profile.service import obtener_medico, obtener_medico_por_usuario
from app.modules.appointments.models import BloqueoAgenda, HorarioMedico, Medico, ServicioMedico
from app.modules.auth.models import Auditoria, Usuario
from app.modules.communications.models import Notificacion
from app.modules.medical_records.models import Paciente
from .schemas import AccionBloqueoResponse, BloqueoCreate, BloqueoResponse, HorarioCreate


ACTIVOS = ("PENDIENTE", "APROBADO")
# Día civil de Bolivia, independiente de la zona del proceso/servidor.
ZONA_AGENDA = timezone(timedelta(hours=-4))


def hoy_agenda() -> date:
    return datetime.now(ZONA_AGENDA).date()


def _rol(user: Usuario) -> str:
    nombre = user.rol.nombre if user.rol else ""
    nombre = "".join(c for c in unicodedata.normalize("NFD", nombre.upper()) if not unicodedata.combining(c))
    if user.id_rol == 1 or nombre in ("ADMIN", "ADMINISTRADOR", "ADMINISTRACION"):
        return "ADMIN"
    return nombre


def _contexto(user: Usuario, tenant_id: int | None, roles=("MEDICO", "RECEPCION")) -> str:
    rol = _rol(user)
    if rol not in roles or (user.rol and user.rol.estado.lower() != "activo"):
        raise HTTPException(403, "No tienes permisos para esta operación de agenda")
    # Un header no concede acceso a una clínica a un usuario sin pertenencia.
    if user.id_clinica is None or tenant_id != user.id_clinica:
        raise HTTPException(403, "Se requiere una clínica asociada al usuario autenticado")
    return rol


def _medico(db, user, tenant_id, id_medico=None):
    rol = _contexto(user, tenant_id)
    if rol == "MEDICO":
        medico = obtener_medico_por_usuario(db, user.id_usuario, current_tenant_id=tenant_id)
        if id_medico is not None and id_medico != medico.id_medico:
            raise HTTPException(403, "Solo puedes gestionar tu propia agenda")
        return medico
    if id_medico is None:
        raise HTTPException(422, "Recepción debe indicar id_medico")
    return obtener_medico(db, id_medico, current_tenant_id=tenant_id)


def _servicio(db, id_servicio):
    servicio = db.get(ServicioMedico, id_servicio)
    if servicio is None:
        raise HTTPException(404, "Servicio médico no encontrado")
    if servicio.estado.lower() != "activo":
        raise HTTPException(409, "El servicio médico está inactivo")
    if servicio.duracion_minutos <= 0 or servicio.hora_inicio >= servicio.hora_fin:
        raise HTTPException(409, "La configuración del servicio médico es inválida")
    return servicio


def _scope(db, model, user, tenant_id, id_medico=None, revisar=False):
    rol = _contexto(user, tenant_id, ("MEDICO", "RECEPCION", "ADMIN") if revisar else ("MEDICO", "RECEPCION"))
    query = db.query(model).join(Medico, model.id_medico == Medico.id_medico).join(
        Usuario, Medico.id_usuario == Usuario.id_usuario
    ).filter(Usuario.id_clinica == tenant_id)
    if rol == "MEDICO" or id_medico is not None:
        if rol == "ADMIN":
            medico = obtener_medico(db, id_medico, current_tenant_id=tenant_id)
        else:
            medico = _medico(db, user, tenant_id, id_medico)
        query = query.filter(model.id_medico == medico.id_medico)
    return query


def _lock_medico(db, id_medico, tenant_id):
    # Serializa altas CU05 del mismo médico sin inventar restricciones en Neon.
    db.query(Medico).join(Usuario).filter(
        Medico.id_medico == id_medico, Usuario.id_clinica == tenant_id
    ).with_for_update(of=Medico).one()


def _auditar(db, user, tenant_id, registro, accion, descripcion):
    # Omitir snapshots evita escribir String sobre los JSONB de la BD real.
    db.add(Auditoria(
        id_clinica=tenant_id, id_usuario=user.id_usuario,
        tabla_afectada=registro.__tablename__,
        registro_id=getattr(registro, "id_bloqueo", None) or getattr(registro, "id_horario", None),
        accion=accion, descripcion=descripcion,
    ))


def _guardar(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        codigo = getattr(exc.orig, "pgcode", None)
        if codigo in ("23505", "23P01") or "UNIQUE constraint failed" in str(exc.orig):
            raise HTTPException(409, "El registro ya existe o el intervalo se solapa") from exc
        raise
    except Exception:
        db.rollback()
        raise


def listar_servicios(db, user, tenant_id):
    _contexto(user, tenant_id)
    return db.query(ServicioMedico).order_by(ServicioMedico.id_servicio).all()


def listar_horarios(db, user, tenant_id, id_medico=None):
    return _scope(db, HorarioMedico, user, tenant_id, id_medico).order_by(HorarioMedico.id_horario).all()


def crear_horario(db: Session, datos: HorarioCreate, user, tenant_id):
    medico = _medico(db, user, tenant_id, datos.id_medico)
    _servicio(db, datos.id_servicio)
    _lock_medico(db, medico.id_medico, tenant_id)
    existente = _scope(db, HorarioMedico, user, tenant_id, medico.id_medico).filter(
        HorarioMedico.id_servicio == datos.id_servicio, HorarioMedico.dia_semana == datos.dia_semana
    ).first()
    if existente:
        raise HTTPException(409, "El horario ya existe; utiliza el cambio de estado para reactivarlo")
    horario = HorarioMedico(id_medico=medico.id_medico, id_servicio=datos.id_servicio,
                            dia_semana=datos.dia_semana, estado="activo")
    db.add(horario)
    # Flush y auditoría se incluyen en la misma transacción que la operación.
    try:
        db.flush()
        _auditar(db, user, tenant_id, horario, "CREAR", "Disponibilidad recurrente creada")
        _guardar(db)
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "pgcode", None) == "23505" or "UNIQUE constraint failed" in str(exc.orig):
            raise HTTPException(409, "El horario ya existe") from exc
        raise
    return horario


def cambiar_estado_horario(db, id_horario, estado, user, tenant_id):
    horario = _scope(db, HorarioMedico, user, tenant_id).filter(
        HorarioMedico.id_horario == id_horario
    ).with_for_update(of=HorarioMedico).first()
    if not horario:
        raise HTTPException(404, "Horario no encontrado")
    if estado == "activo":
        _servicio(db, horario.id_servicio)
    anterior = horario.estado
    horario.estado = estado
    _auditar(db, user, tenant_id, horario, "CAMBIAR_ESTADO", f"Disponibilidad: {anterior} -> {estado}")
    _guardar(db)
    return horario


def listar_bloqueos(db, user, tenant_id, id_medico=None):
    return _scope(db, BloqueoAgenda, user, tenant_id, id_medico, revisar=True).order_by(
        BloqueoAgenda.fecha, BloqueoAgenda.hora_inicio, BloqueoAgenda.id_bloqueo
    ).all()


def _segundos(hora: time):
    return hora.hour * 3600 + hora.minute * 60 + hora.second + hora.microsecond / 1_000_000


def crear_bloqueo(db: Session, datos: BloqueoCreate, user, tenant_id):
    medico = _medico(db, user, tenant_id, datos.id_medico)
    servicio = _servicio(db, datos.id_servicio)
    if _rol(user) == "MEDICO" and datos.fecha != hoy_agenda() + timedelta(days=1):
        raise HTTPException(422, "El médico solo puede solicitar bloqueos para el día siguiente")
    inicio, fin = _segundos(datos.hora_inicio), _segundos(datos.hora_fin)
    base, limite = _segundos(servicio.hora_inicio), _segundos(servicio.hora_fin)
    paso = servicio.duracion_minutos * 60
    if inicio >= fin or inicio < base or fin > limite:
        raise HTTPException(422, "El intervalo debe estar dentro del bloque fijo del servicio")
    if (fin - inicio) % paso or (inicio - base) % paso or (fin - base) % paso:
        raise HTTPException(422, "El intervalo debe respetar la duración y los límites de los slots")
    _lock_medico(db, medico.id_medico, tenant_id)
    solapado = _scope(db, BloqueoAgenda, user, tenant_id, medico.id_medico).filter(
        BloqueoAgenda.id_servicio == datos.id_servicio, BloqueoAgenda.fecha == datos.fecha,
        BloqueoAgenda.estado.in_(ACTIVOS), BloqueoAgenda.hora_inicio < datos.hora_fin,
        BloqueoAgenda.hora_fin > datos.hora_inicio,
    ).first()
    if solapado:
        raise HTTPException(409, "El intervalo se solapa con otro bloqueo pendiente o aprobado")
    bloqueo = BloqueoAgenda(**datos.model_dump(exclude={"id_medico"}), id_medico=medico.id_medico, estado="PENDIENTE")
    db.add(bloqueo)
    try:
        db.flush()
        _auditar(db, user, tenant_id, bloqueo, "SOLICITAR", "Solicitud de bloqueo PENDIENTE")
        _guardar(db)
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "pgcode", None) in ("23P01", "23505"):
            raise HTTPException(409, "El intervalo se solapa con otro bloqueo") from exc
        raise
    return bloqueo


def _citas(db, id_medico, fecha, tenant_id):
    inspector = inspect(db.connection())
    necesarios = {"id_cita", "id_paciente", "id_medico", "fecha_cita", "hora_inicio", "hora_fin"}
    if not inspector.has_table("citas") or not necesarios.issubset(
        {c["name"] for c in inspector.get_columns("citas")}
    ):
        return [], ["No se pudo verificar citas: la tabla o sus columnas requeridas no están disponibles"]
    citas = table("citas", column("id_cita", BigInteger), column("id_paciente", BigInteger),
                  column("id_medico", BigInteger), column("fecha_cita", Date),
                  column("hora_inicio", Time), column("hora_fin", Time))
    consulta = select(citas.c.id_cita, citas.c.id_paciente, citas.c.hora_inicio, citas.c.hora_fin).select_from(
        citas.join(Medico.__table__, citas.c.id_medico == Medico.id_medico).join(
            Usuario.__table__, Medico.id_usuario == Usuario.id_usuario)
    ).where(citas.c.id_medico == id_medico, citas.c.fecha_cita == fecha, Usuario.id_clinica == tenant_id)
    return db.execute(consulta).mappings().all(), []


def _intersecta(inicio, fin, otro_inicio, otro_fin):
    # Horas incompletas: no declarar libre un periodo que no podemos verificar.
    return otro_inicio is None or otro_fin is None or inicio < otro_fin and fin > otro_inicio


def _notificar(db, citas, bloqueo, tenant_id):
    creadas, advertencias = 0, []
    inspector = inspect(db.connection())
    if not citas:
        return creadas, advertencias
    if not inspector.has_table("notificaciones"):
        return 0, ["Citas afectadas sin aviso: la tabla notificaciones no está disponible"]
    if not inspector.has_table("pacientes") or not {"id_paciente", "id_usuario"}.issubset(
        {c["name"] for c in inspector.get_columns("pacientes")}
    ):
        return 0, ["Citas afectadas sin aviso: no se pudo verificar la relación paciente-usuario"]
    for cita in citas:
        # La relación paciente -> usuario existe en Paciente; no se infiere por correo.
        receptor = db.query(Usuario.id_usuario).join(Paciente, Paciente.id_usuario == Usuario.id_usuario).filter(
            Paciente.id_paciente == cita["id_paciente"], Usuario.id_clinica == tenant_id
        ).scalar()
        if receptor is None:
            advertencias.append(f"Cita {cita['id_cita']}: no se pudo determinar un usuario receptor de la clínica")
            continue
        db.add(Notificacion(
            id_usuario=receptor, tipo="REPROGRAMACION", titulo="Cita requiere reprogramación",
            mensaje=f"La cita {cita['id_cita']} del {bloqueo.fecha.isoformat()} requiere reprogramación por un bloqueo de agenda aprobado. La cita no ha sido modificada.",
            estado="PENDIENTE",
        ))
        creadas += 1
    return creadas, advertencias


def cambiar_bloqueo(db, id_bloqueo, accion, user, tenant_id):
    es_admin = accion in ("aprobar", "rechazar")
    _contexto(user, tenant_id, ("ADMIN",) if es_admin else ("MEDICO", "RECEPCION"))
    bloqueo = _scope(db, BloqueoAgenda, user, tenant_id, revisar=es_admin).filter(
        BloqueoAgenda.id_bloqueo == id_bloqueo
    ).populate_existing().with_for_update(of=BloqueoAgenda).first()
    if bloqueo is None:
        raise HTTPException(404, "Bloqueo no encontrado")
    origen, destino = {"aprobar": ("PENDIENTE", "APROBADO"), "rechazar": ("PENDIENTE", "RECHAZADO"),
                       "liberar": ("APROBADO", "LIBERADO")}[accion]
    if bloqueo.estado != origen:
        raise HTTPException(409, f"La acción requiere un bloqueo {origen}")
    afectadas, advertencias, creadas = [], [], 0
    if accion == "aprobar":
        citas, advertencias = _citas(db, bloqueo.id_medico, bloqueo.fecha, tenant_id)
        afectadas = [c for c in citas if _intersecta(bloqueo.hora_inicio, bloqueo.hora_fin, c["hora_inicio"], c["hora_fin"])]
        creadas, avisos = _notificar(db, afectadas, bloqueo, tenant_id)
        advertencias.extend(avisos)
    bloqueo.estado = destino
    _auditar(db, user, tenant_id, bloqueo, accion.upper(), f"Bloqueo: {origen} -> {destino}")
    _guardar(db)
    return AccionBloqueoResponse(**BloqueoResponse.model_validate(bloqueo).model_dump(),
        citas_afectadas=[c["id_cita"] for c in afectadas], notificaciones_creadas=creadas, advertencias=advertencias)


def disponibilidad(db, user, tenant_id, id_medico, fecha, id_servicio):
    medico = _medico(db, user, tenant_id, id_medico)
    servicio = _servicio(db, id_servicio)
    horario = _scope(db, HorarioMedico, user, tenant_id, medico.id_medico).filter(
        HorarioMedico.id_servicio == id_servicio, HorarioMedico.dia_semana == fecha.isoweekday(),
        func.lower(HorarioMedico.estado) == "activo",
    ).first()
    citas, advertencias = _citas(db, medico.id_medico, fecha, tenant_id)
    bloqueos = _scope(db, BloqueoAgenda, user, tenant_id, medico.id_medico).filter(
        BloqueoAgenda.id_servicio == id_servicio, BloqueoAgenda.fecha == fecha,
        BloqueoAgenda.estado.in_(ACTIVOS),
    ).all()
    slots = []
    cursor = datetime.combine(fecha, servicio.hora_inicio)
    fin = datetime.combine(fecha, servicio.hora_fin)
    paso = timedelta(minutes=servicio.duracion_minutos)
    while cursor + paso <= fin:
        inicio_slot, fin_slot = cursor.time(), (cursor + paso).time()
        ocupado = any(_intersecta(inicio_slot, fin_slot, b.hora_inicio, b.hora_fin) for b in bloqueos)
        ocupado = ocupado or any(_intersecta(inicio_slot, fin_slot, c["hora_inicio"], c["hora_fin"]) for c in citas)
        slots.append({"hora_inicio": inicio_slot, "hora_fin": fin_slot,
                      "disponible": bool(horario) and not ocupado and not advertencias})
        cursor += paso
    return {"id_medico": medico.id_medico, "id_servicio": id_servicio, "fecha": fecha,
            "slots": slots, "citas_verificadas": not advertencias, "advertencias": advertencias}
