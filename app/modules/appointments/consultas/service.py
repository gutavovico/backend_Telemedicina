from datetime import date, datetime, time
from typing import List, Optional
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.modules.appointments.models import Cita, Medico, Especialidad
from app.modules.appointments.consultas.schemas import (
    CitaCreate,
    CitaListResponse,
    CitaResponse,
    CitaUpdate,
    HorarioSlot,
)
from app.modules.medical_records.models import Paciente
from app.modules.auth.models import Usuario

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
            medico_nombre = f"Dr(a). {cita.medico.usuario.nombres} {cita.medico.usuario.apellidos}".strip()
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


def crear_cita(db: Session, datos: CitaCreate) -> CitaResponse:
    paciente = db.query(Paciente).filter(Paciente.id_paciente == datos.id_paciente).first()
    if not paciente:
        raise ValueError(f"El paciente con ID {datos.id_paciente} no existe")

    medico = db.query(Medico).filter(Medico.id_medico == datos.id_medico).first()
    if not medico:
        raise ValueError(f"El médico con ID {datos.id_medico} no existe")

    cita_ocupada = (
        db.query(Cita)
        .filter(
            Cita.id_medico == datos.id_medico,
            Cita.fecha_cita == datos.fecha_cita,
            Cita.hora_inicio == datos.hora_inicio,
            Cita.estado != "CANCELADA",
        )
        .first()
    )
    if cita_ocupada:
        raise ValueError("El horario seleccionado ya está ocupado para este médico")

    # Construir fecha_hora_inicio si es posible
    fecha_hora_ini = None
    try:
        partes = datos.hora_inicio.split(":")
        t_ini = time(int(partes[0]), int(partes[1]))
        fecha_hora_ini = datetime.combine(datos.fecha_cita, t_ini)
    except Exception:
        pass

    nueva_cita = Cita(
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
    return formatear_cita_response(nueva_cita)


def obtener_cita_por_id(db: Session, id_cita: int) -> Optional[Cita]:
    return (
        db.query(Cita)
        .options(
            joinedload(Cita.paciente),
            joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Cita.especialidad),
        )
        .filter(Cita.id_cita == id_cita)
        .first()
    )


def listar_citas(
    db: Session,
    q: Optional[str] = None,
    fecha: Optional[date] = None,
    estado: Optional[str] = None,
    id_medico: Optional[int] = None,
    id_paciente: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
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


def actualizar_cita(db: Session, id_cita: int, datos: CitaUpdate) -> Optional[CitaResponse]:
    cita = db.query(Cita).filter(Cita.id_cita == id_cita).first()
    if not cita:
        return None

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
    return formatear_cita_response(cita)


def eliminar_cita(db: Session, id_cita: int) -> bool:
    cita = db.query(Cita).filter(Cita.id_cita == id_cita).first()
    if not cita:
        return False
    db.delete(cita)
    db.commit()
    return True


def obtener_horarios_disponibles(db: Session, id_medico: int, fecha: date) -> List[HorarioSlot]:
    citas_ocupadas = (
        db.query(Cita.hora_inicio)
        .filter(
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
