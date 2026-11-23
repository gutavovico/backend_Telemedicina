import logging

from fastapi import HTTPException, status
from datetime import date, datetime, time
from typing import List, Optional
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.modules.appointments.models import Cita, Medico, Especialidad
from app.modules.appointments.doctor_entity_links.context import (
    resolve_active_medical_link_for_tenant,
)
from app.modules.appointments.consultas.schemas import (
    CitaCreate,
    CitaListResponse,
    CitaResponse,
    CitaUpdate,
    HorarioSlot,
)
from app.modules.medical_records.models import Paciente
from app.modules.auth.models import Clinica, Usuario
from app.core.tenant_status import CANONICAL_SUSPENDED, canonical_tenant_status

logger = logging.getLogger(__name__)

HORARIOS_ESTANDAR = [
    "08:00", "08:30", "09:00", "09:30", "10:00", "10:30",
    "11:00", "11:30", "14:00", "14:30", "15:00", "15:30",
    "16:00", "16:30", "17:00", "17:30"
]


def formatear_cita_response(cita: Cita) -> CitaResponse:
    paciente_nombre = ""
    paciente_ci = ""
    paciente_iniciales = "PA"
    if getattr(cita, "paciente", None):
        paciente_nombre = f"{cita.paciente.nombres} {cita.paciente.apellidos}".strip()
        paciente_ci = f"ID: {cita.paciente.ci}"
        if getattr(cita.paciente, "complemento", None):
            paciente_ci += f"-{cita.paciente.complemento}"

        partes_nombre = cita.paciente.nombres.split() if cita.paciente.nombres else []
        partes_apellido = cita.paciente.apellidos.split() if cita.paciente.apellidos else []
        ini_n = partes_nombre[0][0].upper() if partes_nombre else ""
        ini_a = partes_apellido[0][0].upper() if partes_apellido else ""
        paciente_iniciales = f"{ini_n}{ini_a}" or "PA"

    medico_nombre = ""
    if getattr(cita, "medico", None):
        if getattr(cita.medico, "usuario", None):
            u_nombres = (cita.medico.usuario.nombres or "").strip()
            u_apellidos = (cita.medico.usuario.apellidos or "").strip()
            nombre_completo = f"{u_nombres} {u_apellidos}".strip()
            if nombre_completo.lower().startswith("dr.") or nombre_completo.lower().startswith("dra.") or nombre_completo.lower().startswith("dr(a)."):
                medico_nombre = nombre_completo
            else:
                medico_nombre = f"Dr. {nombre_completo}".strip()
        else:
            medico_nombre = f"Médico Matrícula: {getattr(cita.medico, 'matricula_profesional', cita.id_medico)}"

    especialidad_nombre = ""
    if getattr(cita, "especialidad", None):
        especialidad_nombre = cita.especialidad.nombre
    elif getattr(cita, "medico", None) and getattr(cita.medico, "especialidades", None):
        for me in cita.medico.especialidades:
            if getattr(me, "especialidad", None):
                especialidad_nombre = me.especialidad.nombre
                if getattr(me, "es_principal", False):
                    break

    created_dt = getattr(cita, "created_at", None) or getattr(cita, "fecha_creacion", None) or datetime.now()
    updated_dt = getattr(cita, "updated_at", None) or created_dt

    return CitaResponse(
        id_cita=cita.id_cita,
        id_paciente=cita.id_paciente,
        id_medico=cita.id_medico,
        id_especialidad=cita.id_especialidad,
        fecha_cita=cita.fecha_cita,
        hora_inicio=cita.hora_inicio,
        hora_fin=cita.hora_fin,
        motivo=cita.motivo,
        estado=cita.estado or "PENDIENTE",
        tipo_consulta=getattr(cita, "tipo_consulta", None) or getattr(cita, "modalidad", None) or "TELEMEDICINA",
        notas=cita.notas,
        paciente_nombre=paciente_nombre,
        paciente_ci=paciente_ci,
        paciente_iniciales=paciente_iniciales,
        medico_nombre=medico_nombre,
        especialidad_nombre=especialidad_nombre,
        created_at=created_dt,
        updated_at=updated_dt,
    )


def _rol_efectivo(db: Session, user: Usuario, tenant_id: int) -> str:
    """Rol operativo de la entidad seleccionada, sin caer al rol global."""
    contexto = resolve_active_medical_link_for_tenant(db, user, tenant_id)
    if contexto is not None:
        nombres = {(rol or "").strip().upper() for rol in contexto.roles}
        if nombres & {"ADMIN", "ADMINISTRADOR", "ADMINISTRACION"}:
            return "ADMIN"
        if nombres & {"MEDICO", "MÉDICO", "MEDICO_ESPECIALISTA"}:
            return "MEDICO"
        if "RECEPCION" in nombres or "RECEPCIÓN" in nombres:
            return "RECEPCION"
        return ""
    nombre = (getattr(user, "rol", "") or "").strip().upper()
    if nombre in {"ADMIN", "ADMINISTRADOR", "ADMINISTRACION"}:
        return "ADMIN"
    if nombre in {"MEDICO", "MÉDICO", "MEDICO_ESPECIALISTA"}:
        return "MEDICO"
    if nombre in {"RECEPCION", "RECEPCIÓN"}:
        return "RECEPCION"
    if nombre == "PACIENTE":
        return "PACIENTE"
    return ""


def _medico_pertenece_tenant(db: Session, id_medico: int, tenant_id: int) -> bool:
    return db.query(Medico.id_medico).join(
        Usuario, Medico.id_usuario == Usuario.id_usuario
    ).filter(
        Medico.id_medico == id_medico,
        (Medico.id_clinica == tenant_id) | (Usuario.id_clinica == tenant_id),
    ).first() is not None


def _paciente_pertenece_tenant(db: Session, id_paciente: int, tenant_id: int) -> bool:
    return db.query(Paciente.id_paciente).filter(
        Paciente.id_paciente == id_paciente,
        Paciente.id_clinica == tenant_id,
    ).first() is not None


def _id_medico_propio(
    db: Session, user: Usuario, tenant_id: int
) -> Optional[int]:
    contexto = resolve_active_medical_link_for_tenant(db, user, tenant_id)
    if contexto is not None:
        return contexto.link.id_medico
    return db.query(Medico.id_medico).filter(
        Medico.id_usuario == user.id_usuario
    ).first()


def _verificar_acceso_cita(
    db: Session, cita: Cita, user: Usuario, tenant_id: int
) -> None:
    if _rol_efectivo(db, user, tenant_id) != "MEDICO":
        return
    id_medico_propio = _id_medico_propio(db, user, tenant_id)
    if id_medico_propio is None or int(cita.id_medico) != int(id_medico_propio):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cita no encontrada",
        )


def crear_cita(
    db: Session, datos: CitaCreate, *, tenant_id: int, current_user: Usuario
) -> CitaResponse:
    paciente = db.query(Paciente).filter(Paciente.id_paciente == datos.id_paciente).first()
    if not paciente or not _paciente_pertenece_tenant(db, datos.id_paciente, tenant_id):
        raise ValueError(f"El paciente con ID {datos.id_paciente} no existe")

    medico = db.query(Medico).filter(Medico.id_medico == datos.id_medico).first()
    if not medico or not _medico_pertenece_tenant(db, datos.id_medico, tenant_id):
        raise ValueError(f"El médico con ID {datos.id_medico} no existe")
    clinica = db.query(Clinica).filter(Clinica.id_clinica == tenant_id).first()
    if clinica and canonical_tenant_status(clinica.estado) == CANONICAL_SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación no permitida: el tenant se encuentra suspendido",
        )

    if _rol_efectivo(db, current_user, tenant_id) == "MEDICO":
        contexto = resolve_active_medical_link_for_tenant(db, current_user, tenant_id)
        id_medico_propio = contexto.link.id_medico if contexto is not None else None
        if id_medico_propio is None or int(id_medico_propio) != int(datos.id_medico):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes gestionar tus propias citas",
            )

    cita_ocupada = (
        db.query(Cita)
        .filter(
            Cita.id_clinica == tenant_id,
            Cita.id_medico == datos.id_medico,
            Cita.fecha_cita == datos.fecha_cita,
            Cita.hora_inicio == datos.hora_inicio,
            Cita.estado != "CANCELADA",
        )
        .first()
    )
    if cita_ocupada:
        raise ValueError("El horario seleccionado ya está ocupado para este médico")

    fecha_hora_ini = None
    try:
        partes = datos.hora_inicio.split(":")
        t_ini = time(int(partes[0]), int(partes[1]))
        fecha_hora_ini = datetime.combine(datos.fecha_cita, t_ini)
    except Exception:
        pass

    nueva_cita = Cita(
        id_clinica=tenant_id,
        id_paciente=datos.id_paciente,
        id_medico=datos.id_medico,
        id_especialidad=datos.id_especialidad,
        fecha_cita=datos.fecha_cita,
        hora_inicio=datos.hora_inicio,
        hora_fin=datos.hora_fin,
        fecha_hora_inicio=fecha_hora_ini,
        modalidad=datos.tipo_consulta or "TELEMEDICINA",
        motivo=datos.motivo,
        estado=datos.estado or "PENDIENTE",
        tipo_consulta=datos.tipo_consulta or "TELEMEDICINA",
        notas=datos.notas,
    )
    db.add(nueva_cita)
    db.commit()
    db.refresh(nueva_cita)
    from app.modules.communications.notificaciones.hooks import notificar_cita_creada
    notificar_cita_creada(db, nueva_cita, paciente, medico)
    return formatear_cita_response(nueva_cita)


def obtener_cita_por_id(
    db: Session,
    id_cita: int,
    *,
    tenant_id: int,
    current_user: Optional[Usuario] = None,
) -> Optional[Cita]:
    cita = (
        db.query(Cita)
        .options(
            joinedload(Cita.paciente),
            joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Cita.especialidad),
        )
        .filter(Cita.id_cita == id_cita, Cita.id_clinica == tenant_id)
        .first()
    )
    if cita is not None and current_user is not None:
        _verificar_acceso_cita(db, cita, current_user, tenant_id)
    return cita


def listar_citas(
    db: Session,
    q: Optional[str] = None,
    fecha: Optional[date] = None,
    estado: Optional[str] = None,
    id_medico: Optional[int] = None,
    id_paciente: Optional[int] = None,
    tipo_consulta: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    tenant_id: Optional[int] = None,
    current_user: Optional[Usuario] = None,
) -> CitaListResponse:
    query = (
        db.query(Cita)
        .join(Paciente, Cita.id_paciente == Paciente.id_paciente)
        .join(Medico, Cita.id_medico == Medico.id_medico)
        .outerjoin(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .outerjoin(Especialidad, Cita.id_especialidad == Especialidad.id_especialidad)
        .options(
            joinedload(Cita.paciente),
            joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Cita.especialidad),
        )
    )
    if tenant_id is not None:
        query = query.filter(Cita.id_clinica == tenant_id)
    if tenant_id is not None and current_user is not None:
        rol = _rol_efectivo(db, current_user, tenant_id)
        if rol == "MEDICO":
            id_medico_propio = _id_medico_propio(db, current_user, tenant_id)
            if id_medico_propio is None:
                return CitaListResponse(total=0, page=page, page_size=page_size, items=[])
            query = query.filter(Cita.id_medico == id_medico_propio)
        elif rol == "PACIENTE":
            id_paciente = db.query(Paciente.id_paciente).filter(
                Paciente.id_usuario == current_user.id_usuario,
                Paciente.id_clinica == tenant_id,
            ).first()
            if id_paciente is None:
                return CitaListResponse(total=0, page=page, page_size=page_size, items=[])
            query = query.filter(Cita.id_paciente == id_paciente)

    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Paciente.nombres.ilike(search),
                Paciente.apellidos.ilike(search),
                Paciente.ci.ilike(search),
                Usuario.nombres.ilike(search),
                Usuario.apellidos.ilike(search),
                Especialidad.nombre.ilike(search),
                Cita.motivo.ilike(search),
            )
        )

    if fecha:
        query = query.filter(Cita.fecha_cita == fecha)

    if estado and estado.strip() and estado.upper() != "TODOS":
        query = query.filter(Cita.estado == estado.strip().upper())

    if id_medico:
        query = query.filter(Cita.id_medico == id_medico)

    if id_paciente:
        query = query.filter(Cita.id_paciente == id_paciente)

    if tipo_consulta and tipo_consulta.strip() and tipo_consulta.upper() != 'TODOS':
        tipo = tipo_consulta.strip().upper()
        query = query.filter(or_(Cita.tipo_consulta == tipo, Cita.modalidad == tipo))

    total = query.count()
    offset = (page - 1) * page_size
    citas = query.order_by(Cita.fecha_cita.desc(), Cita.hora_inicio.asc()).offset(offset).limit(page_size).all()

    items = [formatear_cita_response(c) for c in citas]

    return CitaListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items
    )


def _reasignar_lista_espera(db: Session, cita: Cita, origen: str) -> None:
    """Hook CU07: intenta reasignar el cupo liberado sin afectar la operación.

    Un fallo en la reasignación nunca revierte la cancelación o eliminación
    que la originó. La sesión se restaura para no dejar una transacción sucia.
    """
    try:
        from app.modules.appointments.lista_espera.service import (
            reasignar_por_cancelacion,
        )

        reasignar_por_cancelacion(db, cita)
    except Exception as exc:  # noqa: BLE001 - best effort deliberado
        db.rollback()
        logger.warning(
            "CU07: no se pudo reasignar el cupo (%s): %s",
            origen,
            exc,
        )


def actualizar_cita(
    db: Session,
    id_cita: int,
    datos: CitaUpdate,
    *,
    tenant_id: Optional[int] = None,
    current_user: Optional[Usuario] = None,
) -> Optional[CitaResponse]:
    q = db.query(Cita).filter(Cita.id_cita == id_cita)
    if tenant_id is not None:
        q = q.filter(Cita.id_clinica == tenant_id)
    cita = q.first()
    if not cita:
        return None
    if current_user is not None and tenant_id is not None:
        _verificar_acceso_cita(db, cita, current_user, tenant_id)

    estado_anterior = (cita.estado or "").upper()
    update_dict = datos.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if value is not None:
            if key == "estado":
                setattr(cita, key, str(value).upper())
            elif key == "tipo_consulta":
                setattr(cita, "tipo_consulta", value)
                setattr(cita, "modalidad", value)
            else:
                setattr(cita, key, value)

    # Actualizar fecha_hora_inicio si cambió fecha o hora
    if "fecha_cita" in update_dict or "hora_inicio" in update_dict:
        try:
            f = cita.fecha_cita
            partes = cita.hora_inicio.split(":")
            cita.fecha_hora_inicio = datetime.combine(f, time(int(partes[0]), int(partes[1])))
        except Exception:
            pass

    db.commit()
    db.refresh(cita)
    from app.modules.communications.notificaciones.hooks import notificar_cita_actualizada
    notificar_cita_actualizada(
        db,
        cita,
        estado_nuevo=update_dict.get("estado"),
        cambio_horario=("fecha_cita" in update_dict or "hora_inicio" in update_dict),
    )

    if (cita.estado or "").upper() == "CANCELADA" and estado_anterior != "CANCELADA":
        _reasignar_lista_espera(db, cita, "cancelacion")

    return formatear_cita_response(cita)


def eliminar_cita(
    db: Session,
    id_cita: int,
    *,
    tenant_id: int,
    current_user: Optional[Usuario] = None,
) -> bool:
    cita = (
        db.query(Cita)
        .filter(Cita.id_cita == id_cita, Cita.id_clinica == tenant_id)
        .first()
    )
    if not cita:
        return False
    if current_user is not None:
        _verificar_acceso_cita(db, cita, current_user, tenant_id)
    cupo = {
        "id_clinica": cita.id_clinica,
        "id_medico": cita.id_medico,
        "id_especialidad": cita.id_especialidad,
        "fecha_cita": cita.fecha_cita,
        "hora_inicio": cita.hora_inicio,
        "hora_fin": cita.hora_fin,
        "id_servicio": cita.id_servicio,
        "id_cita": cita.id_cita,
    }
    db.delete(cita)
    db.commit()

    try:
        from app.modules.appointments.lista_espera.service import reasignar_turno_liberado

        reasignar_turno_liberado(
            db,
            tenant_id=cupo["id_clinica"],
            id_medico=cupo["id_medico"],
            id_especialidad=cupo["id_especialidad"],
            fecha=cupo["fecha_cita"],
            hora_inicio=cupo["hora_inicio"],
            hora_fin=cupo["hora_fin"],
            id_servicio=cupo["id_servicio"],
            origen="ELIMINACION",
        )
    except Exception as exc:  # noqa: BLE001 - best effort deliberado
        db.rollback()
        logger.warning("CU07: no se pudo reasignar el cupo eliminado %s: %s", cupo["id_cita"], exc)
    return True


def obtener_horarios_disponibles(
    db: Session, id_medico: int, fecha: date, *, tenant_id: int
) -> List[HorarioSlot]:
    if not _medico_pertenece_tenant(db, id_medico, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Médico no encontrado",
        )
    citas_ocupadas = (
        db.query(Cita.hora_inicio)
        .filter(
            Cita.id_clinica == tenant_id,
            Cita.id_medico == id_medico,
            Cita.fecha_cita == fecha,
            Cita.estado != "CANCELADA"
        )
        .all()
    )
    ocupadas_set = {c[0] for c in citas_ocupadas if c[0] is not None}

    return [
        HorarioSlot(hora=h, disponible=(h not in ocupadas_set))
        for h in HORARIOS_ESTANDAR
    ]
