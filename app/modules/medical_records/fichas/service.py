import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.modules.medical_records.fichas.models import FichaClinica
from app.modules.medical_records.fichas.schemas import (
    FichaCancelRequest,
    FichaClinicaUpdate,
    FichaCreate,
    FichaListResponse,
    FichaResponse,
)
from app.modules.medical_records.models import Paciente
from app.modules.appointments.models import Cita, Especialidad, Medico, ServicioMedico
from app.modules.auth.models import Usuario


def generar_correlativo(db: Session, id_clinica: int, fecha_atencion: date) -> str:
    """
    Genera un correlativo alfanumérico secuencial y único por clínica.
    Formato: FICH-YYYYMMDD-XXXX
    """
    date_str = fecha_atencion.strftime("%Y%m%d")
    prefix = f"FICH-{date_str}-"

    count = (
        db.query(func.count(FichaClinica.id_ficha))
        .filter(
            FichaClinica.id_clinica == id_clinica,
            FichaClinica.correlativo.like(f"{prefix}%"),
        )
        .scalar()
        or 0
    )

    sequence = count + 1
    # Asegurar unicidad si hubiera colisiones por borrados o concurrencia
    while True:
        correlativo = f"{prefix}{sequence:04d}"
        exists = (
            db.query(FichaClinica.id_ficha)
            .filter(
                FichaClinica.id_clinica == id_clinica,
                FichaClinica.correlativo == correlativo,
            )
            .first()
        )
        if not exists:
            return correlativo
        sequence += 1


def _to_ficha_response(ficha: FichaClinica) -> FichaResponse:
    """Convierte una entidad FichaClinica a FichaResponse enriquecida."""
    paciente_nombre = None
    paciente_ci = None
    if ficha.paciente:
        paciente_nombre = f"{ficha.paciente.nombres} {ficha.paciente.apellidos}".strip()
        paciente_ci = ficha.paciente.ci

    medico_nombre = None
    if ficha.medico and ficha.medico.usuario:
        medico_nombre = f"Dr. {ficha.medico.usuario.nombres} {ficha.medico.usuario.apellidos}".strip()

    servicio_nombre = ficha.servicio.nombre if ficha.servicio else None
    especialidad_nombre = ficha.especialidad.nombre if ficha.especialidad else None

    return FichaResponse(
        id_ficha=ficha.id_ficha,
        id_clinica=ficha.id_clinica,
        tenant_id=ficha.id_clinica,
        correlativo=ficha.correlativo,
        id_paciente=ficha.id_paciente,
        paciente_id=ficha.id_paciente,
        paciente_nombre=paciente_nombre,
        paciente_ci=paciente_ci,
        id_medico=ficha.id_medico,
        medico_id=ficha.id_medico,
        medico_nombre=medico_nombre,
        id_servicio=ficha.id_servicio,
        servicio_id=ficha.id_servicio,
        servicio_nombre=servicio_nombre,
        id_especialidad=ficha.id_especialidad,
        especialidad_id=ficha.id_especialidad,
        especialidad_nombre=especialidad_nombre,
        id_cita=ficha.id_cita,
        cita_id=ficha.id_cita,
        fecha_emision=ficha.fecha_emision,
        fecha_atencion=ficha.fecha_atencion,
        hora_inicio=ficha.hora_inicio,
        hora_fin=ficha.hora_fin,
        motivo_consulta=ficha.motivo_consulta,
        signos_vitales=ficha.signos_vitales or {},
        secciones_dinamicas=ficha.secciones_dinamicas or {},
        codigo_cie10=ficha.codigo_cie10,
        diagnostico_descripcion=ficha.diagnostico_descripcion,
        id_diagnostico=ficha.id_diagnostico,
        notas_evolucion=ficha.notas_evolucion,
        estado=ficha.estado,
        motivo_cancelacion=ficha.motivo_cancelacion,
        created_at=ficha.created_at,
        updated_at=ficha.updated_at,
    )


def crear_ficha(
    db: Session,
    payload: FichaCreate,
    id_clinica: int,
    current_user: Optional[Usuario] = None,
) -> FichaResponse:
    """
    Emite una ficha clínica validando pertenencia al tenant y previniendo colisiones de turno (409 Conflict).
    """
    # 1. Validar paciente en el tenant
    paciente = (
        db.query(Paciente)
        .filter(
            Paciente.id_paciente == payload.id_paciente,
            (Paciente.id_clinica == id_clinica) | (Paciente.id_clinica == None),
        )
        .first()
    )
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paciente no encontrado en esta clínica",
        )

    # 2. Validar médico en el tenant
    medico = (
        db.query(Medico)
        .join(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .filter(
            Medico.id_medico == payload.id_medico,
            (Usuario.id_clinica == id_clinica) | (Usuario.id_clinica == None),
        )
        .first()
    )
    if not medico:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Médico no encontrado en esta clínica",
        )

    # 3. Control de concurrencia y prevención de colisión de turno (409 Conflict)
    ficha_existente = (
        db.query(FichaClinica)
        .filter(
            FichaClinica.id_clinica == id_clinica,
            FichaClinica.id_medico == payload.id_medico,
            FichaClinica.fecha_atencion == payload.fecha_atencion,
            FichaClinica.hora_inicio == payload.hora_inicio,
            FichaClinica.estado != "CANCELADA",
        )
        .first()
    )
    if ficha_existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El turno seleccionado ya se encuentra ocupado por otra ficha médica o cita clínica",
        )

    # Validar contra citas agendadas activas en ese slot (si no es la misma cita vinculada)
    cita_conflictiva = (
        db.query(Cita)
        .filter(
            Cita.id_medico == payload.id_medico,
            Cita.fecha_cita == payload.fecha_atencion,
            Cita.hora_inicio == payload.hora_inicio,
            Cita.estado.notin_(["CANCELADA", "ELIMINADA"]),
        )
        .first()
    )
    if cita_conflictiva and (payload.id_cita is None or cita_conflictiva.id_cita != payload.id_cita):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El turno seleccionado ya se encuentra ocupado por otra ficha médica o cita clínica",
        )

    # 4. Generar correlativo único
    correlativo = generar_correlativo(db, id_clinica, payload.fecha_atencion)

    # 5. Persistir ficha
    nueva_ficha = FichaClinica(
        id_ficha=str(uuid.uuid4()),
        id_clinica=id_clinica,
        correlativo=correlativo,
        id_paciente=payload.id_paciente,
        id_medico=payload.id_medico,
        id_servicio=payload.id_servicio,
        id_especialidad=payload.id_especialidad,
        id_cita=payload.id_cita,
        fecha_emision=datetime.now(),
        fecha_atencion=payload.fecha_atencion,
        hora_inicio=payload.hora_inicio,
        hora_fin=payload.hora_fin,
        motivo_consulta=payload.motivo_consulta,
        signos_vitales=payload.signos_vitales or {},
        secciones_dinamicas=payload.secciones_dinamicas or {},
        estado="EMITIDA",
    )

    db.add(nueva_ficha)
    db.commit()
    db.refresh(nueva_ficha)

    return _to_ficha_response(nueva_ficha)


def listar_fichas(
    db: Session,
    id_clinica: int,
    id_paciente: Optional[int] = None,
    id_medico: Optional[int] = None,
    id_especialidad: Optional[int] = None,
    fecha: Optional[date] = None,
    estado: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> FichaListResponse:
    """Consulta paginada y filtrable de fichas del tenant."""
    query = (
        db.query(FichaClinica)
        .options(
            joinedload(FichaClinica.paciente),
            joinedload(FichaClinica.medico).joinedload(Medico.usuario),
            joinedload(FichaClinica.servicio),
            joinedload(FichaClinica.especialidad),
        )
        .filter(FichaClinica.id_clinica == id_clinica)
    )

    if id_paciente is not None:
        query = query.filter(FichaClinica.id_paciente == id_paciente)
    if id_medico is not None:
        query = query.filter(FichaClinica.id_medico == id_medico)
    if id_especialidad is not None:
        query = query.filter(FichaClinica.id_especialidad == id_especialidad)
    if fecha is not None:
        query = query.filter(FichaClinica.fecha_atencion == fecha)
    if estado is not None:
        query = query.filter(FichaClinica.estado == estado.upper())

    total = query.count()
    fichas = (
        query.order_by(FichaClinica.fecha_atencion.desc(), FichaClinica.hora_inicio.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    items = [_to_ficha_response(f) for f in fichas]
    return FichaListResponse(total=total, items=items)


def obtener_ficha_por_id(db: Session, id_ficha: str, id_clinica: int) -> FichaClinica:
    """Busca una ficha por ID asegurando aislamiento multitenant."""
    ficha = (
        db.query(FichaClinica)
        .options(
            joinedload(FichaClinica.paciente),
            joinedload(FichaClinica.medico).joinedload(Medico.usuario),
            joinedload(FichaClinica.servicio),
            joinedload(FichaClinica.especialidad),
        )
        .filter(
            FichaClinica.id_ficha == id_ficha,
            FichaClinica.id_clinica == id_clinica,
        )
        .first()
    )
    if not ficha:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ficha médica no encontrada en esta clínica",
        )
    return ficha


def obtener_ficha_detalle(db: Session, id_ficha: str, id_clinica: int) -> FichaResponse:
    """Retorna el DTO de respuesta para el detalle de una ficha."""
    ficha = obtener_ficha_por_id(db, id_ficha, id_clinica)
    return _to_ficha_response(ficha)


def actualizar_clinica_ficha(
    db: Session,
    id_ficha: str,
    payload: FichaClinicaUpdate,
    id_clinica: int,
    current_user: Optional[Usuario] = None,
) -> FichaResponse:
    """
    Actualización médica de la ficha: signos vitales, secciones dinámicas JSONB,
    diagnósticos CIE-10 y notas de evolución.
    """
    ficha = obtener_ficha_por_id(db, id_ficha, id_clinica)

    if ficha.estado == "CANCELADA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede modificar una ficha médica cancelada",
        )

    if payload.signos_vitales is not None:
        current_sv = dict(ficha.signos_vitales or {})
        current_sv.update(payload.signos_vitales)
        ficha.signos_vitales = current_sv

    if payload.secciones_dinamicas is not None:
        current_sd = dict(ficha.secciones_dinamicas or {})
        current_sd.update(payload.secciones_dinamicas)
        ficha.secciones_dinamicas = current_sd

    if payload.codigo_cie10 is not None:
        ficha.codigo_cie10 = payload.codigo_cie10
    if payload.diagnostico_descripcion is not None:
        ficha.diagnostico_descripcion = payload.diagnostico_descripcion
    if payload.id_diagnostico is not None:
        ficha.id_diagnostico = payload.id_diagnostico
    if payload.notas_evolucion is not None:
        ficha.notas_evolucion = payload.notas_evolucion
    if payload.estado is not None:
        ficha.estado = payload.estado.upper()

    ficha.updated_at = datetime.now()
    db.commit()
    db.refresh(ficha)

    return _to_ficha_response(ficha)


def cancelar_ficha(
    db: Session,
    id_ficha: str,
    motivo: str,
    id_clinica: int,
    current_user: Optional[Usuario] = None,
) -> FichaResponse:
    """Cancela una ficha médica si no se encuentra en estado FINALIZADA."""
    ficha = obtener_ficha_por_id(db, id_ficha, id_clinica)

    if ficha.estado == "FINALIZADA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede cancelar una ficha médica que ya ha sido finalizada",
        )

    ficha.estado = "CANCELADA"
    ficha.motivo_cancelacion = motivo
    ficha.updated_at = datetime.now()
    db.commit()
    db.refresh(ficha)

    return _to_ficha_response(ficha)
