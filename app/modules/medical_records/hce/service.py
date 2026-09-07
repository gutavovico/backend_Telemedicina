from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.audit import registrar_auditoria
from app.modules.appointments.models import Cita, Medico
from app.modules.auth.models import Usuario
from app.modules.medical_records.hce.models import Consulta, Diagnostico, HistoriaClinica
from app.modules.medical_records.hce.schemas import ConsultaCreateRequest
from app.modules.medical_records.models import Paciente
from app.modules.medical_records.patient_profile.service import get_patient_by_id, get_patient_by_user_id


def _generar_numero_historia(db: Session, tenant_id: Optional[int] = None) -> str:
    """Genera un numero de historia unico con formato HCE-YYYY-NNNNNN scoped por tenant."""
    year = datetime.now().year
    prefix = f"HCE-{year}-"
    stmt = (
        select(HistoriaClinica)
        .where(HistoriaClinica.numero_historia.like(f"{prefix}%"))
    )
    if tenant_id is not None:
        stmt = stmt.where(HistoriaClinica.id_clinica == tenant_id)
    stmt = stmt.order_by(HistoriaClinica.id_historia.desc())

    ultima = db.execute(stmt).scalars().first()
    siguiente = 1
    if ultima and ultima.numero_historia:
        try:
            siguiente = int(ultima.numero_historia.split("-")[-1]) + 1
        except (ValueError, IndexError):
            siguiente = 1
    return f"HCE-{year}-{siguiente:06d}"


def get_historia_by_paciente(
    db: Session, id_paciente: int, tenant_id: Optional[int] = None
) -> Optional[HistoriaClinica]:
    """Obtiene la historia clínica asociada a un paciente filtrando por tenant."""
    stmt = select(HistoriaClinica).where(HistoriaClinica.id_paciente == id_paciente)
    if tenant_id is not None:
        stmt = stmt.where(HistoriaClinica.id_clinica == tenant_id)
    return db.execute(stmt).scalars().first()


def get_historia_by_id(
    db: Session, id_historia: int, tenant_id: Optional[int] = None
) -> Optional[HistoriaClinica]:
    """Obtiene la historia clínica por ID filtrando por tenant."""
    stmt = select(HistoriaClinica).where(HistoriaClinica.id_historia == id_historia)
    if tenant_id is not None:
        stmt = stmt.where(HistoriaClinica.id_clinica == tenant_id)
    return db.execute(stmt).scalars().first()


def get_or_create_historia_by_paciente(
    db: Session, id_paciente: int, tenant_id: Optional[int] = None
) -> HistoriaClinica:
    """
    Obtiene la historia clínica del paciente en el tenant actual o la inicializa
    a partir de los datos base del paciente.
    """
    # Validar que el paciente existe y pertenece al tenant
    paciente = get_patient_by_id(db, id_paciente, tenant_id=tenant_id)
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paciente no encontrado en este centro médico",
        )

    historia = get_historia_by_paciente(db, id_paciente, tenant_id=tenant_id)
    if historia:
        return historia

    clinica_id = tenant_id if tenant_id is not None else getattr(paciente, "id_clinica", 1) or 1
    historia = HistoriaClinica(
        id_clinica=clinica_id,
        id_paciente=id_paciente,
        numero_historia=_generar_numero_historia(db, tenant_id=clinica_id),
        alergias=paciente.alergias,
        antecedentes_personales=paciente.antecedentes_patologicos,
    )
    db.add(historia)
    db.flush()
    return historia


def get_consulta_by_id(
    db: Session, id_consulta: int, current_user: Usuario, tenant_id: Optional[int] = None
) -> Consulta:
    """Obtiene una consulta clínica validando aislamiento multitenant y permisos de acceso."""
    stmt = (
        select(Consulta)
        .options(joinedload(Consulta.diagnosticos), joinedload(Consulta.historia))
        .where(Consulta.id_consulta == id_consulta)
    )
    if tenant_id is not None:
        stmt = stmt.where(Consulta.id_clinica == tenant_id)

    consulta = db.execute(stmt).scalars().first()
    if not consulta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consulta médica no encontrada",
        )

    # Si el usuario es PACIENTE, verificar que sea el dueño de la historia clínica
    rol_nombre = current_user.rol.nombre.upper() if current_user.rol else ""
    if rol_nombre == "PACIENTE" or current_user.id_rol == 4:
        perfil_paciente = get_patient_by_user_id(db, current_user.id_usuario, tenant_id=tenant_id)
        if not perfil_paciente or consulta.historia.id_paciente != perfil_paciente.id_paciente:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para consultar notas médicas de otro paciente",
            )

    return consulta


def registrar_consulta_clinica(
    db: Session,
    id_paciente: int,
    payload: ConsultaCreateRequest,
    medico_usuario: Usuario,
    medico: Medico,
    ip_cliente: str,
    tenant_id: Optional[int] = None,
) -> Consulta:
    """
    Registra una consulta clínica estructurada (SOAP + signos vitales + CIE-10),
    asocia la clínica (multitenancy), finaliza la cita y registra auditoría.
    """
    target_clinica = tenant_id if tenant_id is not None else medico_usuario.id_clinica or 1

    # Validar paciente dentro del tenant
    paciente = get_patient_by_id(db, id_paciente, tenant_id=target_clinica)
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paciente no encontrado en este centro médico",
        )

    # Validar cita
    cita: Optional[Cita] = db.get(Cita, payload.id_cita)
    if not cita:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cita no encontrada",
        )
    if cita.id_paciente != id_paciente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La cita no pertenece al paciente indicado",
        )
    if cita.id_medico != medico.id_medico:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cita no está asignada al médico autenticado",
        )
    if cita.estado and cita.estado.upper() in ("FINALIZADA", "COMPLETADA", "CANCELADA"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La cita ya fue finalizada o no puede ser atendida",
        )

    # Obtener o inicializar historia clínica para este tenant
    historia = get_or_create_historia_by_paciente(db, id_paciente, tenant_id=target_clinica)

    try:
        consulta = Consulta(
            id_clinica=target_clinica,
            id_historia=historia.id_historia,
            id_cita=payload.id_cita,
            id_medico=medico.id_medico,
            motivo_consulta=payload.motivo_consulta,
            sintomas=payload.sintomas,
            examen_fisico=payload.examen_fisico,
            signos_vitales=payload.signos_vitales.model_dump() if payload.signos_vitales else None,
            observaciones=payload.observaciones,
            evolucion=payload.evolucion,
            plan_medico=payload.plan_medico,
            datos_especialidad=payload.datos_especialidad,
        )
        db.add(consulta)
        db.flush()

        for diag_in in payload.diagnosticos:
            diagnostico = Diagnostico(
                id_consulta=consulta.id_consulta,
                codigo_cie=diag_in.codigo_cie,
                descripcion=diag_in.descripcion,
                tipo=diag_in.tipo.value,
                observaciones=diag_in.observaciones,
            )
            db.add(diagnostico)

        # Transición de estado de la cita
        cita.estado = "FINALIZADA"

        # Registro inmutable de auditoría médica
        registrar_auditoria(
            db,
            id_usuario=medico_usuario.id_usuario,
            id_clinica=target_clinica,
            tabla_afectada="consultas",
            registro_id=consulta.id_consulta,
            accion="INSERT",
            descripcion="Registro de consulta médica y evolución clínica",
            datos_nuevos=payload.model_dump(mode="json"),
            direccion_ip=ip_cliente,
        )

        db.commit()
        db.refresh(consulta)
        return consulta
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al persistir la consulta médica: {exc}",
        )
