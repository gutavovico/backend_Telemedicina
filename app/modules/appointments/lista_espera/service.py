"""Lista de espera y reasignacion automatica de cupos liberados (CU07).

Reglas:
- Aislamiento estricto por `id_clinica` (tenant).
- Un paciente solo opera sus propias inscripciones.
- La reasignacion crea una cita PENDIENTE y notifica; nunca revierte la
  cancelacion o liberacion que la origino.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.appointments.models import (
    Cita,
    Especialidad,
    ListaEspera,
    Medico,
    MedicoEspecialidad,
    ServicioMedico,
)
from app.modules.auth.models import Usuario
from app.modules.communications.models import Notificacion
from app.modules.medical_records.models import Paciente
from app.modules.notificaciones.service import enviar_push_usuario
from .schemas import InscripcionEsperaCreate, InscripcionEsperaResponse, OfrecerTurnoCommand

logger = logging.getLogger(__name__)

ESTADOS_ACTIVOS = ("EN_ESPERA", "OFRECIDO")
ESTADOS_CITA_LIBRE = ("CANCELADA", "ELIMINADA")
DURACION_DEFECTO_MIN = 20
STAFF_ROLES = ("ADMIN", "MEDICO", "RECEPCION")
ROL_PACIENTE = "PACIENTE"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _rol(user: Usuario) -> str:
    rol_val = getattr(user, "rol", None)
    if isinstance(rol_val, str):
        nombre = rol_val
    elif rol_val is not None:
        nombre = getattr(rol_val, "nombre", "") or ""
    else:
        nombre = ""
    if not nombre:
        rel = getattr(user, "rol_rel", None)
        nombre = (getattr(rel, "nombre", "") or "") if rel is not None else ""
    nombre = "".join(
        c for c in unicodedata.normalize("NFD", nombre.upper()) if not unicodedata.combining(c)
    )
    if getattr(user, "id_rol", None) == 1 or nombre in ("ADMIN", "ADMINISTRADOR", "ADMINISTRACION"):
        return "ADMIN"
    return nombre


def _es_paciente(user: Usuario) -> bool:
    return _rol(user) == ROL_PACIENTE or getattr(user, "id_rol", None) == 4


def _es_staff(user: Usuario) -> bool:
    return _rol(user) in STAFF_ROLES or getattr(user, "id_rol", None) in (1, 2, 3)


def _hora_str(valor) -> Optional[str]:
    if valor is None:
        return None
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    texto = str(valor).strip()
    if not texto:
        return None
    partes = texto.split(":")
    if len(partes) >= 2:
        return f"{partes[0].zfill(2)}:{partes[1].zfill(2)}"
    return texto[:5]


def _hora_time(valor) -> Optional[time]:
    if valor is None or isinstance(valor, time):
        return valor
    for formato in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(str(valor).strip(), formato).time()
        except ValueError:
            continue
    return None


def _nombre_paciente(paciente: Optional[Paciente]) -> str:
    if paciente is None:
        return "Paciente"
    return f"{paciente.nombres or ''} {paciente.apellidos or ''}".strip() or "Paciente"


def _nombre_medico(medico: Optional[Medico]) -> Optional[str]:
    if medico is None:
        return None
    usuario = getattr(medico, "usuario", None)
    if usuario is not None:
        nombre = f"{usuario.nombres or ''} {usuario.apellidos or ''}".strip()
        if nombre:
            return nombre
    return f"Medico {medico.id_medico}"


def _resolver_paciente(
    db: Session, datos: InscripcionEsperaCreate, user: Usuario, tenant_id: int
) -> Paciente:
    if _es_paciente(user):
        paciente = db.execute(
            select(Paciente).where(Paciente.id_usuario == user.id_usuario)
        ).scalars().first()
        if paciente is None:
            raise HTTPException(404, "Perfil de paciente no encontrado")
        if paciente.id_clinica is not None and paciente.id_clinica != tenant_id:
            raise HTTPException(404, "Paciente no encontrado")
        return paciente

    if not datos.id_paciente:
        raise HTTPException(422, "El staff debe indicar id_paciente")
    paciente = db.execute(
        select(Paciente).where(
            Paciente.id_paciente == datos.id_paciente,
            or_(Paciente.id_clinica == tenant_id, Paciente.id_clinica.is_(None)),
        )
    ).scalars().first()
    if paciente is None:
        raise HTTPException(404, "Paciente no encontrado")
    return paciente


def _validar_medico(db: Session, id_medico: Optional[int], tenant_id: int) -> Optional[Medico]:
    if not id_medico:
        return None
    medico = db.execute(
        select(Medico).where(
            Medico.id_medico == id_medico,
            or_(Medico.id_clinica == tenant_id, Medico.id_clinica.is_(None)),
        )
    ).scalars().first()
    if medico is None:
        raise HTTPException(404, "Medico no encontrado")
    return medico


def _validar_especialidad(db: Session, id_especialidad: Optional[int]) -> Optional[Especialidad]:
    if not id_especialidad:
        return None
    especialidad = db.get(Especialidad, id_especialidad)
    if especialidad is None:
        raise HTTPException(404, "Especialidad no encontrada")
    return especialidad


def _especialidad_principal(db: Session, id_medico: int) -> Optional[int]:
    fila = db.execute(
        select(MedicoEspecialidad)
        .where(MedicoEspecialidad.id_medico == id_medico)
        .order_by(MedicoEspecialidad.es_principal.desc())
    ).scalars().first()
    return fila.id_especialidad if fila is not None else None


def _duracion_servicio(db: Session, id_servicio: Optional[int]) -> int:
    if not id_servicio:
        return DURACION_DEFECTO_MIN
    servicio = db.get(ServicioMedico, id_servicio)
    if servicio is None or not servicio.duracion_minutos:
        return DURACION_DEFECTO_MIN
    return int(servicio.duracion_minutos)


def _slot_ocupado(db: Session, id_medico: int, fecha: date, hora_inicio: str) -> bool:
    variantes = [hora_inicio, f"{hora_inicio}:00"]
    return db.execute(
        select(Cita.id_cita).where(
            Cita.id_medico == id_medico,
            Cita.fecha_cita == fecha,
            Cita.hora_inicio.in_(variantes),
            or_(Cita.estado.is_(None), Cita.estado.notin_(ESTADOS_CITA_LIBRE)),
        )
    ).first() is not None


def _posiciones(db: Session, tenant_id: int, items: list[ListaEspera]) -> dict[int, int]:
    activas = db.execute(
        select(ListaEspera).where(
            ListaEspera.id_clinica == tenant_id,
            ListaEspera.estado == "EN_ESPERA",
        )
    ).scalars().all()
    grupos: dict[tuple, list[ListaEspera]] = {}
    for entrada in activas:
        grupos.setdefault((entrada.id_medico, entrada.id_especialidad), []).append(entrada)

    posiciones: dict[int, int] = {}
    for lista in grupos.values():
        lista.sort(
            key=lambda e: (
                -(e.prioridad or 0),
                str(e.fecha_creacion or ""),
                e.id_lista_espera,
            )
        )
        for indice, entrada in enumerate(lista, start=1):
            posiciones[entrada.id_lista_espera] = indice

    for entrada in items:
        if entrada.estado == "EN_ESPERA":
            entrada._posicion = posiciones.get(entrada.id_lista_espera, 0)
        elif entrada.estado == "OFRECIDO":
            entrada._posicion = 1
        else:
            entrada._posicion = 0
    return posiciones


def _to_response(db: Session, entrada: ListaEspera) -> InscripcionEsperaResponse:
    paciente = db.get(Paciente, entrada.id_paciente)
    medico = db.get(Medico, entrada.id_medico) if entrada.id_medico else None
    especialidad = db.get(Especialidad, entrada.id_especialidad) if entrada.id_especialidad else None
    return InscripcionEsperaResponse(
        id_lista_espera=entrada.id_lista_espera,
        id_paciente=entrada.id_paciente,
        paciente_nombre=_nombre_paciente(paciente),
        id_medico=entrada.id_medico,
        medico_nombre=_nombre_medico(medico),
        id_especialidad=entrada.id_especialidad,
        especialidad_nombre=especialidad.nombre if especialidad else None,
        fecha_deseada=entrada.fecha_deseada.isoformat() if entrada.fecha_deseada else None,
        estado=entrada.estado,
        prioridad=entrada.prioridad or 0,
        posicion=getattr(entrada, "_posicion", 0),
        motivo=entrada.motivo,
        id_cita_ofrecida=entrada.id_cita_ofrecida,
        fecha_creacion=entrada.fecha_creacion,
    )


def _obtener(db: Session, id_lista_espera: int, user: Usuario, tenant_id: int) -> ListaEspera:
    entrada = db.execute(
        select(ListaEspera).where(
            ListaEspera.id_lista_espera == id_lista_espera,
            ListaEspera.id_clinica == tenant_id,
        )
    ).scalars().first()
    if entrada is None:
        raise HTTPException(404, "Inscripcion no encontrada")
    if _es_paciente(user):
        paciente = db.execute(
            select(Paciente).where(Paciente.id_usuario == user.id_usuario)
        ).scalars().first()
        if paciente is None or entrada.id_paciente != paciente.id_paciente:
            raise HTTPException(404, "Inscripcion no encontrada")
    return entrada


def _notificar_oferta(db: Session, entrada: ListaEspera, cita: Cita) -> None:
    paciente = db.get(Paciente, entrada.id_paciente)
    if paciente is None or paciente.id_usuario is None:
        return
    medico = db.get(Medico, cita.id_medico)
    nombre_medico = _nombre_medico(medico) or "el especialista"
    fecha = cita.fecha_cita.isoformat() if cita.fecha_cita else ""
    hora = _hora_str(cita.hora_inicio) or ""
    titulo = "Turno disponible"
    mensaje = (
        f"Se libero un turno con {nombre_medico} el {fecha} a las {hora}. "
        "Confirma o rechaza en tu lista de espera."
    )
    db.add(
        Notificacion(
            id_clinica=entrada.id_clinica,
            id_usuario=paciente.id_usuario,
            rol_destinatario="PACIENTE",
            tipo="TURNO_REASIGNADO",
            categoria="CITAS",
            canal="PUSH",
            canal_badge="Push",
            titulo=titulo,
            mensaje=mensaje,
            recurso_tipo="LISTA_ESPERA",
            recurso_id=str(entrada.id_lista_espera),
            enlace_accion="/lista-espera",
            estado="PENDIENTE",
        )
    )
    try:
        enviar_push_usuario(
            db,
            paciente.id_usuario,
            entrada.id_clinica,
            titulo,
            mensaje,
            {
                "tipo": "TURNO_REASIGNADO",
                "id_lista_espera": entrada.id_lista_espera,
                "id_cita": cita.id_cita,
            },
        )
    except Exception as exc:  # El push nunca bloquea la reasignacion.
        logger.warning("Push CU07 omitido para la inscripcion %s: %s", entrada.id_lista_espera, exc)


def _notificar_respuesta(
    db: Session,
    entrada: ListaEspera,
    cita: Optional[Cita],
    *,
    confirmada: bool,
) -> None:
    """Registra y envía el aviso cuando el paciente acepta o rechaza el turno.

    La bandeja de CU20 consulta la tabla `notificaciones`, así que este registro
    hace aparecer el heads-up en la APK aunque el proveedor FCM no esté disponible.
    """
    paciente = db.get(Paciente, entrada.id_paciente)
    if paciente is None or paciente.id_usuario is None:
        return

    medico = db.get(Medico, cita.id_medico) if cita is not None else None
    nombre_medico = _nombre_medico(medico) or "el especialista"
    fecha = cita.fecha_cita.isoformat() if cita is not None and cita.fecha_cita else ""
    hora = _hora_str(cita.hora_inicio) if cita is not None else ""

    if confirmada:
        tipo = "TURNO_CONFIRMADO"
        titulo = "Turno confirmado"
        mensaje = f"Confirmaste tu turno con {nombre_medico} el {fecha} a las {hora}."
    else:
        tipo = "TURNO_RECHAZADO"
        titulo = "Turno rechazado"
        mensaje = (
            f"Rechazaste el turno con {nombre_medico} el {fecha} a las {hora}. "
            "El cupo se ofrecerá al siguiente paciente."
        )

    db.add(
        Notificacion(
            id_clinica=entrada.id_clinica,
            id_usuario=paciente.id_usuario,
            rol_destinatario="PACIENTE",
            tipo=tipo,
            categoria="CITAS",
            canal="PUSH",
            canal_badge="Push",
            titulo=titulo,
            mensaje=mensaje,
            recurso_tipo="LISTA_ESPERA",
            recurso_id=str(entrada.id_lista_espera),
            enlace_accion="/lista-espera",
            estado="PENDIENTE",
        )
    )
    try:
        enviar_push_usuario(
            db,
            paciente.id_usuario,
            entrada.id_clinica,
            titulo,
            mensaje,
            {
                "tipo": tipo,
                "id_lista_espera": entrada.id_lista_espera,
                "id_cita": cita.id_cita if cita is not None else "",
            },
        )
    except Exception as exc:  # El push nunca bloquea la respuesta del paciente.
        logger.warning("Push CU07 omitido para la respuesta %s: %s", entrada.id_lista_espera, exc)


def _crear_oferta(
    db: Session,
    entrada: ListaEspera,
    *,
    id_medico: int,
    id_especialidad: Optional[int],
    fecha: date,
    hora_inicio: str,
    hora_fin: str,
    id_servicio: Optional[int] = None,
) -> Optional[Cita]:
    if _slot_ocupado(db, id_medico, fecha, hora_inicio):
        return None

    inicio = _hora_time(hora_inicio) or time(0, 0)
    fin = _hora_time(hora_fin) or time(0, 0)
    cita = Cita(
        id_clinica=entrada.id_clinica,
        id_paciente=entrada.id_paciente,
        id_medico=id_medico,
        id_especialidad=id_especialidad,
        id_servicio=id_servicio,
        fecha_cita=fecha,
        hora_inicio=_hora_str(hora_inicio),
        hora_fin=_hora_str(hora_fin),
        fecha_hora_inicio=datetime.combine(fecha, inicio),
        fecha_hora_fin=datetime.combine(fecha, fin),
        modalidad="PRESENCIAL",
        motivo="Reasignacion automatica de lista de espera (CU07)",
        estado="PENDIENTE",
        tipo_consulta="PRESENCIAL",
    )
    db.add(cita)
    db.flush()

    entrada.estado = "OFRECIDO"
    entrada.id_cita_ofrecida = cita.id_cita
    entrada.fecha_ofrecimiento = _ahora()
    _notificar_oferta(db, entrada, cita)
    return cita


def crear_inscripcion(
    db: Session, datos: InscripcionEsperaCreate, user: Usuario, tenant_id: int
) -> InscripcionEsperaResponse:
    if not (_es_paciente(user) or _es_staff(user)):
        raise HTTPException(403, "Rol no autorizado para la lista de espera")

    paciente = _resolver_paciente(db, datos, user, tenant_id)
    _validar_medico(db, datos.id_medico, tenant_id)
    _validar_especialidad(db, datos.id_especialidad)

    duplicada = db.execute(
        select(ListaEspera.id_lista_espera).where(
            ListaEspera.id_clinica == tenant_id,
            ListaEspera.id_paciente == paciente.id_paciente,
            ListaEspera.estado.in_(ESTADOS_ACTIVOS),
            ListaEspera.id_medico.is_(None) if datos.id_medico is None else ListaEspera.id_medico == datos.id_medico,
            ListaEspera.id_especialidad.is_(None)
            if datos.id_especialidad is None
            else ListaEspera.id_especialidad == datos.id_especialidad,
        )
    ).first()
    if duplicada is not None:
        raise HTTPException(409, "Ya existe una inscripcion activa para ese medico y especialidad")

    prioridad = 0 if _es_paciente(user) else (datos.prioridad or 0)
    entrada = ListaEspera(
        id_clinica=tenant_id,
        id_paciente=paciente.id_paciente,
        id_medico=datos.id_medico,
        id_especialidad=datos.id_especialidad,
        fecha_deseada=datos.fecha_deseada,
        estado="EN_ESPERA",
        prioridad=prioridad,
        motivo=datos.motivo,
    )
    db.add(entrada)
    db.commit()
    db.refresh(entrada)
    _posiciones(db, tenant_id, [entrada])
    return _to_response(db, entrada)


def listar_inscripciones(
    db: Session,
    user: Usuario,
    tenant_id: int,
    *,
    estado: Optional[str] = None,
    id_medico: Optional[int] = None,
    id_especialidad: Optional[int] = None,
    fecha_deseada: Optional[date] = None,
    page: int = 1,
    page_size: int = 50,
):
    condiciones = [ListaEspera.id_clinica == tenant_id]
    if _es_paciente(user):
        paciente = db.execute(
            select(Paciente).where(Paciente.id_usuario == user.id_usuario)
        ).scalars().first()
        if paciente is None:
            return 0, []
        condiciones.append(ListaEspera.id_paciente == paciente.id_paciente)
    elif not _es_staff(user):
        raise HTTPException(403, "Rol no autorizado para la lista de espera")

    if estado:
        condiciones.append(ListaEspera.estado == estado.strip().upper())
    if id_medico:
        condiciones.append(ListaEspera.id_medico == id_medico)
    if id_especialidad:
        condiciones.append(ListaEspera.id_especialidad == id_especialidad)
    if fecha_deseada:
        condiciones.append(ListaEspera.fecha_deseada == fecha_deseada)

    total = db.execute(
        select(func.count()).select_from(ListaEspera).where(*condiciones)
    ).scalar_one()
    items = db.execute(
        select(ListaEspera)
        .where(*condiciones)
        .order_by(ListaEspera.prioridad.desc(), ListaEspera.fecha_creacion.asc(), ListaEspera.id_lista_espera.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    _posiciones(db, tenant_id, items)
    return total, items


def mis_inscripciones(db: Session, user: Usuario, tenant_id: int) -> list[InscripcionEsperaResponse]:
    if not _es_paciente(user):
        raise HTTPException(403, "Solo el paciente puede consultar su lista de espera")
    paciente = db.execute(
        select(Paciente).where(Paciente.id_usuario == user.id_usuario)
    ).scalars().first()
    if paciente is None:
        return []
    items = db.execute(
        select(ListaEspera)
        .where(
            ListaEspera.id_clinica == tenant_id,
            ListaEspera.id_paciente == paciente.id_paciente,
        )
        .order_by(ListaEspera.fecha_creacion.desc(), ListaEspera.id_lista_espera.desc())
    ).scalars().all()
    _posiciones(db, tenant_id, items)
    return [_to_response(db, entrada) for entrada in items]


def salir(db: Session, id_lista_espera: int, user: Usuario, tenant_id: int) -> InscripcionEsperaResponse:
    entrada = _obtener(db, id_lista_espera, user, tenant_id)
    if entrada.estado not in ESTADOS_ACTIVOS:
        raise HTTPException(409, "La inscripcion ya no esta activa")

    slot = None
    if entrada.estado == "OFRECIDO" and entrada.id_cita_ofrecida:
        cita = db.get(Cita, entrada.id_cita_ofrecida)
        if cita is not None:
            slot = {
                "tenant_id": entrada.id_clinica,
                "id_medico": cita.id_medico,
                "id_especialidad": cita.id_especialidad,
                "fecha": cita.fecha_cita,
                "hora_inicio": _hora_str(cita.hora_inicio),
                "hora_fin": _hora_str(cita.hora_fin),
                "id_servicio": cita.id_servicio,
            }
            cita.estado = "CANCELADA"

    entrada.estado = "CANCELADO"
    entrada.fecha_respuesta = _ahora()
    db.commit()
    db.refresh(entrada)

    if slot and slot.get("fecha") and slot.get("id_medico") and slot.get("hora_inicio"):
        try:
            reasignar_turno_liberado(db, **slot)
        except Exception as exc:
            db.rollback()
            logger.warning("No se pudo reasignar tras salida CU07: %s", exc)

    _posiciones(db, tenant_id, [entrada])
    return _to_response(db, entrada)


def confirmar(db: Session, id_lista_espera: int, user: Usuario, tenant_id: int) -> InscripcionEsperaResponse:
    entrada = _obtener(db, id_lista_espera, user, tenant_id)
    if entrada.estado != "OFRECIDO" or not entrada.id_cita_ofrecida:
        raise HTTPException(409, "La inscripcion no tiene un turno ofrecido")

    cita = db.get(Cita, entrada.id_cita_ofrecida)
    if cita is None or (cita.estado or "").upper() in ESTADOS_CITA_LIBRE:
        raise HTTPException(409, "El turno ofrecido ya no esta disponible")

    cita.estado = "CONFIRMADA"
    entrada.estado = "CONFIRMADO"
    entrada.fecha_respuesta = _ahora()
    _notificar_respuesta(db, entrada, cita, confirmada=True)
    db.commit()
    db.refresh(entrada)
    _posiciones(db, tenant_id, [entrada])
    return _to_response(db, entrada)


def rechazar(db: Session, id_lista_espera: int, user: Usuario, tenant_id: int) -> InscripcionEsperaResponse:
    entrada = _obtener(db, id_lista_espera, user, tenant_id)
    if entrada.estado != "OFRECIDO" or not entrada.id_cita_ofrecida:
        raise HTTPException(409, "La inscripcion no tiene un turno ofrecido")

    cita = db.get(Cita, entrada.id_cita_ofrecida)
    slot = None
    if cita is not None:
        slot = {
            "tenant_id": entrada.id_clinica,
            "id_medico": cita.id_medico,
            "id_especialidad": cita.id_especialidad,
            "fecha": cita.fecha_cita,
            "hora_inicio": _hora_str(cita.hora_inicio),
            "hora_fin": _hora_str(cita.hora_fin),
            "id_servicio": cita.id_servicio,
        }
        cita.estado = "CANCELADA"

    entrada.estado = "RECHAZADO"
    entrada.fecha_respuesta = _ahora()
    _notificar_respuesta(db, entrada, cita, confirmada=False)
    db.commit()
    db.refresh(entrada)

    if slot and slot.get("fecha") and slot.get("id_medico") and slot.get("hora_inicio"):
        try:
            reasignar_turno_liberado(db, **slot)
        except Exception as exc:
            db.rollback()
            logger.warning("No se pudo ofrecer al siguiente candidato CU07: %s", exc)

    _posiciones(db, tenant_id, [entrada])
    return _to_response(db, entrada)


def ofrecer_manual(
    db: Session,
    id_lista_espera: int,
    datos: OfrecerTurnoCommand,
    user: Usuario,
    tenant_id: int,
) -> InscripcionEsperaResponse:
    if not _es_staff(user):
        raise HTTPException(403, "Solo el staff puede ofrecer turnos manualmente")
    entrada = _obtener(db, id_lista_espera, user, tenant_id)
    if entrada.estado != "EN_ESPERA":
        raise HTTPException(409, "La inscripcion no esta en espera")

    id_medico = datos.id_medico or entrada.id_medico
    if not id_medico:
        raise HTTPException(400, "Debes indicar id_medico para ofrecer el turno")
    medico = _validar_medico(db, id_medico, tenant_id)
    if medico is None:
        raise HTTPException(404, "Medico no encontrado")

    hora_inicio = _hora_str(datos.hora_inicio)
    inicio = _hora_time(hora_inicio)
    if inicio is None:
        raise HTTPException(400, "Hora de inicio invalida")
    if datos.hora_fin:
        hora_fin = _hora_str(datos.hora_fin)
        fin = _hora_time(hora_fin)
        if fin is None or fin <= inicio:
            raise HTTPException(400, "La hora de fin debe ser posterior al inicio")
    else:
        duracion = _duracion_servicio(db, None)
        fin_dt = datetime.combine(datos.fecha, inicio) + timedelta(minutes=duracion)
        hora_fin = fin_dt.strftime("%H:%M")

    id_especialidad = entrada.id_especialidad or _especialidad_principal(db, id_medico)
    cita = _crear_oferta(
        db,
        entrada,
        id_medico=id_medico,
        id_especialidad=id_especialidad,
        fecha=datos.fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
    )
    if cita is None:
        raise HTTPException(409, "El cupo ya esta ocupado")

    db.commit()
    db.refresh(entrada)
    _posiciones(db, tenant_id, [entrada])
    return _to_response(db, entrada)


def reasignar_turno_liberado(
    db: Session,
    *,
    tenant_id: Optional[int],
    id_medico: Optional[int],
    id_especialidad: Optional[int],
    fecha: Optional[date],
    hora_inicio: Optional[str],
    hora_fin: Optional[str] = None,
    id_servicio: Optional[int] = None,
    origen: str = "CANCELACION",
) -> Optional[InscripcionEsperaResponse]:
    """Ofrece el cupo liberado al primer candidato elegible.

    No lanza excepciones de negocio: si no hay candidato o el cupo esta
    ocupado, devuelve None. Los errores inesperados se propagan para que el
    llamador los registre y decida si revierte solo su propia transaccion.
    """
    if not tenant_id or not id_medico or not fecha or not hora_inicio:
        return None
    if _slot_ocupado(db, id_medico, fecha, hora_inicio):
        return None

    condiciones = [
        ListaEspera.id_clinica == tenant_id,
        ListaEspera.estado == "EN_ESPERA",
        or_(ListaEspera.fecha_deseada.is_(None), ListaEspera.fecha_deseada <= fecha),
        or_(
            ListaEspera.id_medico == id_medico,
            and_(
                ListaEspera.id_medico.is_(None),
                or_(
                    ListaEspera.id_especialidad.is_(None),
                    ListaEspera.id_especialidad == id_especialidad,
                )
                if id_especialidad
                else ListaEspera.id_especialidad.is_(None),
            ),
        ),
    ]
    candidato = db.execute(
        select(ListaEspera)
        .where(*condiciones)
        .order_by(
            ListaEspera.prioridad.desc(),
            ListaEspera.fecha_creacion.asc(),
            ListaEspera.id_lista_espera.asc(),
        )
        .limit(1)
    ).scalars().first()
    if candidato is None:
        return None

    if not id_especialidad:
        id_especialidad = candidato.id_especialidad or _especialidad_principal(db, id_medico)
    if not hora_fin:
        duracion = _duracion_servicio(db, id_servicio)
        inicio = _hora_time(hora_inicio) or time(0, 0)
        hora_fin = (datetime.combine(fecha, inicio) + timedelta(minutes=duracion)).strftime("%H:%M")

    cita = _crear_oferta(
        db,
        candidato,
        id_medico=id_medico,
        id_especialidad=id_especialidad,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        id_servicio=id_servicio,
    )
    if cita is None:
        db.rollback()
        return None

    db.commit()
    db.refresh(candidato)
    _posiciones(db, tenant_id, [candidato])
    logger.info(
        "CU07 reasignacion (%s): cupo %s %s %s ofrecido a la inscripcion %s",
        origen,
        id_medico,
        fecha,
        hora_inicio,
        candidato.id_lista_espera,
    )
    return _to_response(db, candidato)


def reasignar_por_cancelacion(db: Session, cita: Cita) -> Optional[InscripcionEsperaResponse]:
    """Hook CU25: intenta reasignar el cupo de una cita cancelada."""
    tenant_id = cita.id_clinica
    if tenant_id is None and cita.id_medico:
        medico = db.get(Medico, cita.id_medico)
        tenant_id = medico.id_clinica if medico is not None else None
    return reasignar_turno_liberado(
        db,
        tenant_id=tenant_id,
        id_medico=cita.id_medico,
        id_especialidad=cita.id_especialidad,
        fecha=cita.fecha_cita,
        hora_inicio=_hora_str(cita.hora_inicio),
        hora_fin=_hora_str(cita.hora_fin),
        id_servicio=cita.id_servicio,
        origen="CANCELACION",
    )


def reasignar_por_bloqueo(db: Session, bloqueo) -> Optional[InscripcionEsperaResponse]:
    """Hook CU05: al liberar un bloqueo, ofrece el inicio de la franja."""
    medico = db.get(Medico, bloqueo.id_medico)
    tenant_id = medico.id_clinica if medico is not None else None
    if tenant_id is None or bloqueo.fecha is None or bloqueo.hora_inicio is None:
        return None
    hora_inicio = _hora_str(bloqueo.hora_inicio)
    duracion = _duracion_servicio(db, getattr(bloqueo, "id_servicio", None))
    inicio = _hora_time(hora_inicio) or time(0, 0)
    hora_fin = (datetime.combine(bloqueo.fecha, inicio) + timedelta(minutes=duracion)).strftime("%H:%M")
    return reasignar_turno_liberado(
        db,
        tenant_id=tenant_id,
        id_medico=bloqueo.id_medico,
        id_especialidad=_especialidad_principal(db, bloqueo.id_medico),
        fecha=bloqueo.fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        id_servicio=getattr(bloqueo, "id_servicio", None),
        origen="LIBERACION_BLOQUEO",
    )


def serializar(db: Session, entrada: ListaEspera) -> InscripcionEsperaResponse:
    """Serializa una inscripcion ya posicionada por `_posiciones`."""
    return _to_response(db, entrada)

