from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.modules.appointments.models import Cita, Medico, Especialidad
from app.modules.appointments.schemas import (
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
    if cita.paciente:
        paciente_nombre = f"{cita.paciente.nombres} {cita.paciente.apellidos}".strip()
        paciente_ci = f"ID: {cita.paciente.ci}"
        if cita.paciente.complemento:
            paciente_ci += f"-{cita.paciente.complemento}"
        
        partes_nombre = cita.paciente.nombres.split()
        partes_apellido = cita.paciente.apellidos.split()
        ini_n = partes_nombre[0][0].upper() if partes_nombre else ""
        ini_a = partes_apellido[0][0].upper() if partes_apellido else ""
        paciente_iniciales = f"{ini_n}{ini_a}" or "PA"

    medico_nombre = ""
    if cita.medico and cita.medico.usuario:
        medico_nombre = f"Dr(a). {cita.medico.usuario.nombres} {cita.medico.usuario.apellidos}".strip()
    elif cita.medico:
        medico_nombre = f"Médico Matrícula: {cita.medico.matricula_profesional}"

    especialidad_nombre = ""
    if cita.especialidad:
        especialidad_nombre = cita.especialidad.nombre
    elif cita.medico and cita.medico.especialidades:
        for me in cita.medico.especialidades:
            if me.especialidad:
                especialidad_nombre = me.especialidad.nombre
                if me.es_principal:
                    break

    return CitaResponse(
        id_cita=cita.id_cita,
        id_paciente=cita.id_paciente,
        id_medico=cita.id_medico,
        id_especialidad=cita.id_especialidad,
        fecha_cita=cita.fecha_cita,
        hora_inicio=cita.hora_inicio,
        hora_fin=cita.hora_fin,
        motivo=cita.motivo,
        estado=cita.estado,
        tipo_consulta=cita.tipo_consulta,
        notas=cita.notas,
        paciente_nombre=paciente_nombre,
        paciente_ci=paciente_ci,
        paciente_iniciales=paciente_iniciales,
        medico_nombre=medico_nombre,
        especialidad_nombre=especialidad_nombre,
        created_at=cita.created_at or datetime.now(),
        updated_at=cita.updated_at or datetime.now(),
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

    nueva_cita = Cita(
        id_paciente=datos.id_paciente,
        id_medico=datos.id_medico,
        id_especialidad=datos.id_especialidad,
        fecha_cita=datos.fecha_cita,
        hora_inicio=datos.hora_inicio,
        hora_fin=datos.hora_fin,
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
            else:
                setattr(cita, key, value)

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
    ocupadas_set = {c[0] for c in citas_ocupadas}

    return [
        HorarioSlot(hora=h, disponible=(h not in ocupadas_set))
        for h in HORARIOS_ESTANDAR
    ]

