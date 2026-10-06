"""Fila virtual del día CU08 sobre tablas existentes (sin DDL nuevo).

La cola se calcula al vuelo desde `citas` del médico+fecha con estado en
(PENDIENTE, CONFIRMADA, EN_CURSO). Las pausas se modelan con
`BloqueoAgenda` en APROBADO y los avisos con `Notificacion` TURNO_PROXIMO.
Precedentes: `agenda/service.py` (scope por clínica, `_a_hora`, notificar).
"""
from datetime import date, datetime, time, timedelta, timezone
import unicodedata

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.appointments.agenda.schemas import BloqueoResponse
from app.modules.appointments.doctor_profile.service import (
    obtener_medico,
    obtener_medico_por_usuario,
)
from app.modules.appointments.models import (
    BloqueoAgenda,
    Cita,
    HorarioMedico,
    Medico,
    ServicioMedico,
)
from app.modules.auth.models import Usuario
from app.modules.communications.models import Notificacion
from app.modules.medical_records.models import Paciente
from .schemas import PausaCreate


ESTADOS_FILA = ("PENDIENTE", "CONFIRMADA", "EN_CURSO")
ESTADOS_FUERA = ("ATENDIDA", "PERDIDA", "CANCELADA", "COMPLETADA", "ELIMINADA", "FINALIZADA")
DURACION_DEFECTO_MIN = 20
UMBRAL_DEMORA_MIN = 30
UMBRAL_PROXIMO = 2
# Día civil de Bolivia, independiente de la zona del proceso/servidor.
ZONA_COLA = timezone(timedelta(hours=-4))


def ahora_cola() -> datetime:
    return datetime.now(ZONA_COLA)


def hoy_cola() -> date:
    return ahora_cola().date()


def _rol(user: Usuario) -> str:
    # `Usuario.rol` es una property que devuelve str (nombre del rol), no el objeto Rol.
    # Se soportan ambos: str directo o objeto con `.nombre`, con fallback a `rol_rel`.
    rol_val = getattr(user, "rol", None)
    if isinstance(rol_val, str):
        nombre = rol_val
    elif rol_val is not None:
        nombre = getattr(rol_val, "nombre", "") or ""
    else:
        nombre = ""
    if not nombre:
        rel = getattr(user, "rol_rel", None)
        nombre = getattr(rel, "nombre", "") or "" if rel is not None else ""
    nombre = "".join(c for c in unicodedata.normalize("NFD", nombre.upper()) if not unicodedata.combining(c))
    if user.id_rol == 1 or nombre in ("ADMIN", "ADMINISTRADOR", "ADMINISTRACION"):
        return "ADMIN"
    return nombre


def _a_hora(valor):
    """Normaliza `time`, texto 'HH:MM[:SS]' o None a `time | None` (precedente CU05)."""
    if valor is None or isinstance(valor, time):
        return valor
    texto = str(valor).strip()
    for formato in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(texto, formato).time()
        except ValueError:
            continue
    return None


def _exigir_clinica(user: Usuario, tenant_id: int | None) -> None:
    if user.id_clinica is None or tenant_id != user.id_clinica:
        raise HTTPException(403, "Se requiere una clínica asociada al usuario autenticado")


def _medico_staff(db: Session, user: Usuario, tenant_id: int | None, id_medico: int | None = None) -> Medico:
    """MEDICO solo su fila; RECEPCION exige id_medico. Sin ADMIN de clínica (matriz HU CU08)."""
    rol = _rol(user)
    if rol not in ("MEDICO", "RECEPCION"):
        raise HTTPException(403, "Operación de fila virtual restringida a médico o recepción (CU08)")
    _exigir_clinica(user, tenant_id)
    if rol == "MEDICO":
        medico = obtener_medico_por_usuario(db, user.id_usuario, current_tenant_id=tenant_id)
        if id_medico is not None and id_medico != medico.id_medico:
            raise HTTPException(403, "Solo puedes consultar tu propia fila virtual")
        return medico
    if id_medico is None:
        raise HTTPException(422, "Recepción debe indicar id_medico")
    return obtener_medico(db, id_medico, current_tenant_id=tenant_id)


def _nombre_medico(db: Session, medico: Medico) -> str:
    usuario = db.query(Usuario).filter(Usuario.id_usuario == medico.id_usuario).first()
    if usuario and (usuario.nombres or usuario.apellidos):
        return f"{usuario.nombres or ''} {usuario.apellidos or ''}".strip()
    return f"Médico #{medico.id_medico}"


def _nombre_paciente(db: Session, id_paciente: int) -> str:
    paciente = db.get(Paciente, id_paciente)
    if paciente is not None and (getattr(paciente, "nombres", None) or getattr(paciente, "apellidos", None)):
        return f"{paciente.nombres or ''} {paciente.apellidos or ''}".strip()
    return f"Paciente #{id_paciente}"


def _citas_fila(db: Session, id_medico: int, fecha: date, tenant_id: int) -> list[Cita]:
    citas = (
        db.query(Cita)
        .join(Medico, Cita.id_medico == Medico.id_medico)
        .join(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .filter(
            Cita.id_medico == id_medico,
            Cita.fecha_cita == fecha,
            Usuario.id_clinica == tenant_id,
            or_(Cita.id_clinica == tenant_id, Cita.id_clinica.is_(None)),
        )
        .all()
    )
    en_fila = [c for c in citas if (c.estado or "PENDIENTE").upper() in ESTADOS_FILA]
    en_fila.sort(key=lambda c: (_a_hora(c.hora_inicio) or time(23, 59), c.id_cita))
    return en_fila


def _duracion_medico(db: Session, id_medico: int) -> int:
    vals = [
        r[0]
        for r in db.query(ServicioMedico.duracion_minutos)
        .join(HorarioMedico, HorarioMedico.id_servicio == ServicioMedico.id_servicio)
        .filter(HorarioMedico.id_medico == id_medico, ServicioMedico.duracion_minutos > 0)
        .all()
    ]
    if not vals:
        vals = [
            r[0]
            for r in db.query(ServicioMedico.duracion_minutos)
            .filter(ServicioMedico.duracion_minutos > 0)
            .all()
        ]
    if not vals:
        return DURACION_DEFECTO_MIN
    return max(1, round(sum(vals) / len(vals)))


def _duracion_cita(db: Session, cita: Cita, dur_medico: int) -> int:
    if cita.id_servicio:
        servicio = db.get(ServicioMedico, cita.id_servicio)
        if servicio is not None and (servicio.duracion_minutos or 0) > 0:
            return int(servicio.duracion_minutos)
    return dur_medico


def _pausa_vigente(db: Session, id_medico: int, fecha: date, ahora_hora: time, tenant_id: int):
    """Bloqueo APROBADO que solapa el instante dado. Retorna (min_restantes, motivo, fin) o None."""
    bloqueo = (
        db.query(BloqueoAgenda)
        .join(Medico, BloqueoAgenda.id_medico == Medico.id_medico)
        .join(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .filter(
            BloqueoAgenda.id_medico == id_medico,
            BloqueoAgenda.fecha == fecha,
            BloqueoAgenda.estado == "APROBADO",
            Usuario.id_clinica == tenant_id,
        )
        .order_by(BloqueoAgenda.hora_fin)
        .all()
    )
    for b in bloqueo:
        inicio, fin = _a_hora(b.hora_inicio), _a_hora(b.hora_fin)
        if inicio is None or fin is None:
            continue
        if inicio <= ahora_hora < fin:
            restantes = (fin.hour - ahora_hora.hour) * 60 + (fin.minute - ahora_hora.minute)
            return max(0, restantes), (b.motivo or "").strip(), fin
    return None


def computar_cola(db: Session, id_medico: int, fecha: date, tenant_id: int, ahora=None) -> dict:
    ahora = ahora or ahora_cola()
    citas = _citas_fila(db, id_medico, fecha, tenant_id)
    medico = db.get(Medico, id_medico)
    dur_medico = _duracion_medico(db, id_medico)
    pausa = _pausa_vigente(db, id_medico, fecha, ahora.time(), tenant_id)
    pausa_min = pausa[0] if pausa else 0

    entradas, acumulado = [], 0
    for posicion, cita in enumerate(citas, start=1):
        estado = (cita.estado or "PENDIENTE").upper()
        duracion = _duracion_cita(db, cita, dur_medico)
        eta = 0 if estado == "EN_CURSO" else acumulado + pausa_min
        hora = _a_hora(cita.hora_inicio)
        entradas.append({
            "id_cita": cita.id_cita,
            "id_paciente": cita.id_paciente,
            "hora": hora.strftime("%H:%M") if hora else "--:--",
            "estado": estado,
            "posicion": posicion,
            "eta_minutos": eta,
            "paciente_nombre": _nombre_paciente(db, cita.id_paciente),
            "check_in": cita.check_in.isoformat() if cita.check_in else None,
        })
        acumulado += duracion

    if not entradas:
        estado_cola, mensaje = "SIN_TURNOS", "No hay turnos pendientes para esta fecha."
    elif pausa:
        estado_cola = "PAUSADA"
        mensaje = f"Atención pausada hasta las {pausa[2].strftime('%H:%M')} por {pausa[1] or 'imprevisto'}"
    else:
        primera = next((e for e in entradas if e["estado"] != "EN_CURSO"), None)
        atraso = 0
        if primera is not None:
            cita_primera = next((c for c in citas if c.id_cita == primera["id_cita"]), None)
            hora_primera = _a_hora(cita_primera.hora_inicio) if cita_primera is not None else None
            if hora_primera is not None:
                delta = (ahora.time().hour - hora_primera.hour) * 60 + (ahora.time().minute - hora_primera.minute)
                atraso = max(0, delta)
        if atraso > UMBRAL_DEMORA_MIN:
            estado_cola = "DEMORADA"
            if atraso >= 60:
                horas, resto = divmod(atraso, 60)
                demora_txt = f"{horas} h {resto:02d} min" if resto else f"{horas} h"
            else:
                demora_txt = f"{atraso} minutos"
            mensaje = f"La atención presenta una demora aproximada de {demora_txt}"
        else:
            estado_cola, mensaje = "NORMAL", None

    return {
        "id_medico": id_medico,
        "medico_nombre": _nombre_medico(db, medico) if medico else f"Médico #{id_medico}",
        "fecha": fecha.isoformat(),
        "estado_cola": estado_cola,
        "mensaje_cola": mensaje,
        "duracion_promedio_min": dur_medico,
        "total_pendientes": len(entradas),
        "entradas": entradas,
    }


def ver_cola(db: Session, user: Usuario, tenant_id: int, id_medico: int | None, fecha: date) -> dict:
    medico = _medico_staff(db, user, tenant_id, id_medico)
    return computar_cola(db, medico.id_medico, fecha, tenant_id)


def mi_turno(db: Session, user: Usuario, tenant_id: int) -> dict:
    if _rol(user) != "PACIENTE" and user.id_rol != 4:
        raise HTTPException(403, "La consulta de turno propio es exclusiva del paciente (CU08)")
    _exigir_clinica(user, tenant_id)
    paciente = (
        db.query(Paciente)
        .join(Usuario, Paciente.id_usuario == Usuario.id_usuario)
        .filter(Paciente.id_usuario == user.id_usuario, Usuario.id_clinica == tenant_id)
        .first()
    )
    if paciente is None:
        raise HTTPException(404, "El usuario autenticado no tiene expediente de paciente")
    hoy = hoy_cola()
    candidatas = (
        db.query(Cita)
        .join(Medico, Cita.id_medico == Medico.id_medico)
        .join(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .filter(
            Cita.id_paciente == paciente.id_paciente,
            Cita.fecha_cita == hoy,
            Usuario.id_clinica == tenant_id,
            or_(Cita.id_clinica == tenant_id, Cita.id_clinica.is_(None)),
        )
        .all()
    )
    candidatas = [c for c in candidatas if (c.estado or "PENDIENTE").upper() in ESTADOS_FILA]
    candidatas.sort(key=lambda c: (_a_hora(c.hora_inicio) or time(23, 59), c.id_cita))
    if not candidatas:
        return {
            "id_cita": 0, "hora": "--:--", "estado": "SIN_TURNOS", "posicion": 0,
            "eta_minutos": 0, "delante": 0, "proximo": False, "estado_cola": "SIN_TURNOS",
            "mensaje_cola": "No tienes turnos pendientes hoy.",
            "medico_nombre": "", "fecha": hoy.isoformat(),
        }
    cita = candidatas[0]
    cola = computar_cola(db, cita.id_medico, hoy, tenant_id)
    entrada = next(e for e in cola["entradas"] if e["id_cita"] == cita.id_cita)
    return {
        "id_cita": cita.id_cita,
        "hora": entrada["hora"],
        "estado": entrada["estado"],
        "posicion": entrada["posicion"],
        "eta_minutos": entrada["eta_minutos"],
        "delante": entrada["posicion"] - 1,
        "proximo": entrada["posicion"] <= UMBRAL_PROXIMO,
        "estado_cola": cola["estado_cola"],
        "mensaje_cola": cola["mensaje_cola"],
        "medico_nombre": cola["medico_nombre"],
        "fecha": cola["fecha"],
    }


def _cita_en_fila(db: Session, id_cita: int, id_medico: int, tenant_id: int) -> Cita:
    cita = (
        db.query(Cita)
        .join(Medico, Cita.id_medico == Medico.id_medico)
        .join(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .filter(
            Cita.id_cita == id_cita,
            Cita.id_medico == id_medico,
            Usuario.id_clinica == tenant_id,
            or_(Cita.id_clinica == tenant_id, Cita.id_clinica.is_(None)),
        )
        .first()
    )
    if cita is None:
        raise HTTPException(404, "Cita no encontrada en la fila virtual de la clínica")
    if (cita.estado or "PENDIENTE").upper() in ESTADOS_FUERA:
        raise HTTPException(400, "La cita ya salió de la fila virtual")
    return cita


def _notificar_proximos(db: Session, cola: dict, tenant_id: int) -> int:
    creadas = 0
    for entrada in cola["entradas"]:
        if entrada["posicion"] > UMBRAL_PROXIMO:
            continue
        receptor = (
            db.query(Usuario.id_usuario)
            .join(Paciente, Paciente.id_usuario == Usuario.id_usuario)
            .filter(Paciente.id_paciente == entrada["id_paciente"], Usuario.id_clinica == tenant_id)
            .scalar()
        )
        if receptor is None:
            continue
        db.add(Notificacion(
            id_usuario=receptor, tipo="TURNO_PROXIMO", titulo="Tu turno está próximo",
            mensaje=f"Tu cita de las {entrada['hora']} está en posición {entrada['posicion']} de la fila virtual.",
            estado="PENDIENTE",
        ))
        creadas += 1
    return creadas


def _avanzar_tras_marcar(db: Session, medico: Medico, fecha: date, tenant_id: int) -> dict:
    pendientes = _citas_fila(db, medico.id_medico, fecha, tenant_id)
    if pendientes and not any((c.estado or "").upper() == "EN_CURSO" for c in pendientes):
        pendientes[0].estado = "EN_CURSO"
    db.flush()
    cola = computar_cola(db, medico.id_medico, fecha, tenant_id)
    _notificar_proximos(db, cola, tenant_id)
    db.commit()
    return cola


def _resolver_cita_staff(db: Session, user: Usuario, tenant_id: int, id_cita: int):
    """Resuelve (cita, medico) para avanzar/perdida: MEDICO solo su fila (404 ajeno),
    RECEPCION cualquier cita del tenant (404 si es de otra clínica)."""
    rol = _rol(user)
    if rol not in ("MEDICO", "RECEPCION"):
        raise HTTPException(403, "Operación de fila virtual restringida a médico o recepción (CU08)")
    _exigir_clinica(user, tenant_id)
    if rol == "MEDICO":
        medico = obtener_medico_por_usuario(db, user.id_usuario, current_tenant_id=tenant_id)
        cita = _cita_en_fila(db, id_cita, medico.id_medico, tenant_id)
        return cita, medico
    candidatas = (
        db.query(Cita)
        .join(Medico, Cita.id_medico == Medico.id_medico)
        .join(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .filter(Cita.id_cita == id_cita, Usuario.id_clinica == tenant_id,
                or_(Cita.id_clinica == tenant_id, Cita.id_clinica.is_(None)))
        .all()
    )
    if not candidatas:
        raise HTTPException(404, "Cita no encontrada en la fila virtual de la clínica")
    cita = candidatas[0]
    if (cita.estado or "PENDIENTE").upper() in ESTADOS_FUERA:
        raise HTTPException(400, "La cita ya salió de la fila virtual")
    return cita, db.get(Medico, cita.id_medico)


def avanzar(db: Session, user: Usuario, tenant_id: int, id_cita: int) -> dict:
    cita, medico = _resolver_cita_staff(db, user, tenant_id, id_cita)
    cita.estado = "ATENDIDA"
    if cita.check_in is None:
        cita.check_in = ahora_cola().replace(tzinfo=None)
    return _avanzar_tras_marcar(db, medico, cita.fecha_cita, tenant_id)


def marcar_perdida(db: Session, user: Usuario, tenant_id: int, id_cita: int) -> dict:
    cita, medico = _resolver_cita_staff(db, user, tenant_id, id_cita)
    cita.estado = "PERDIDA"
    return _avanzar_tras_marcar(db, medico, cita.fecha_cita, tenant_id)


def registrar_pausa(db: Session, user: Usuario, tenant_id: int, datos: PausaCreate) -> BloqueoAgenda:
    medico = _medico_staff(db, user, tenant_id, datos.id_medico)
    try:
        fecha = date.fromisoformat(datos.fecha)
    except ValueError:
        raise HTTPException(400, "Fecha inválida, use YYYY-MM-DD")
    if fecha < hoy_cola():
        raise HTTPException(400, "La pausa no puede registrarse en una fecha pasada")
    hora_inicio, hora_fin = _a_hora(datos.hora_inicio), _a_hora(datos.hora_fin)
    if hora_inicio is None or hora_fin is None or hora_inicio >= hora_fin:
        raise HTTPException(400, "La franja de pausa es inválida")
    servicio = (
        db.query(ServicioMedico)
        .join(HorarioMedico, HorarioMedico.id_servicio == ServicioMedico.id_servicio)
        .filter(HorarioMedico.id_medico == medico.id_medico)
        .order_by(ServicioMedico.id_servicio)
        .first()
    )
    if servicio is None:
        servicio = db.query(ServicioMedico).order_by(ServicioMedico.id_servicio).first()
    if servicio is None:
        raise HTTPException(409, "El médico no tiene servicios configurados para registrar la pausa")
    solapa = (
        db.query(BloqueoAgenda)
        .filter(
            BloqueoAgenda.id_medico == medico.id_medico,
            BloqueoAgenda.fecha == fecha,
            BloqueoAgenda.estado == "APROBADO",
            BloqueoAgenda.hora_inicio < hora_fin,
            BloqueoAgenda.hora_fin > hora_inicio,
        )
        .first()
    )
    if solapa is not None:
        raise HTTPException(409, "La pausa se solapa con otro bloqueo aprobado")
    bloqueo = BloqueoAgenda(
        id_medico=medico.id_medico, id_servicio=servicio.id_servicio, fecha=fecha,
        hora_inicio=hora_inicio, hora_fin=hora_fin, motivo=datos.motivo.strip(), estado="APROBADO",
    )
    db.add(bloqueo)
    db.commit()
    db.refresh(bloqueo)
    return bloqueo
