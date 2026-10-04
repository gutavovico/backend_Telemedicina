import math
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from app.modules.medical_records.models import Paciente
from app.modules.medical_records.patient_profile.schemas import (
    PacienteCreateRequest,
    PacienteUpdateRequest,
    PacienteProfilePatchRequest
)


def get_patient_by_id(db: Session, id_paciente: int, tenant_id: Optional[int] = None) -> Optional[Paciente]:
    """Obtiene un paciente por su ID primario, opcionalmente filtrado por tenant."""
    query = db.query(Paciente).filter(Paciente.id_paciente == id_paciente)
    if tenant_id is not None:
        query = query.filter(Paciente.id_clinica == tenant_id)
    return query.first()


def get_patient_by_ci(db: Session, ci: str, complemento: Optional[str] = "", tenant_id: Optional[int] = None) -> Optional[Paciente]:
    """Obtiene un paciente por su Carnet de Identidad y Complemento con scope de tenant."""
    comp = complemento or ""
    query = db.query(Paciente).filter(
        and_(
            Paciente.ci == ci.strip(),
            func.coalesce(Paciente.complemento, "") == comp.strip()
        )
    )
    if tenant_id is not None:
        query = query.filter(Paciente.id_clinica == tenant_id)
    return query.first()


def get_patient_by_user_id(db: Session, id_usuario: int, tenant_id: Optional[int] = None) -> Optional[Paciente]:
    """Obtiene el expediente del paciente vinculado a una cuenta de usuario."""
    query = db.query(Paciente).filter(Paciente.id_usuario == id_usuario)
    if tenant_id is not None:
        query = query.filter(Paciente.id_clinica == tenant_id)
    return query.first()


def list_patients(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    q: Optional[str] = None,
    ci: Optional[str] = None,
    estado: Optional[str] = "ACTIVO",
    tenant_id: Optional[int] = None,
) -> Tuple[List[Paciente], int, int]:
    """
    Lista pacientes con paginación, filtros de búsqueda y totalización.
    Retorna: (items, total_records, total_pages)
    """
    query = db.query(Paciente)

    if tenant_id is not None:
        query = query.filter(Paciente.id_clinica == tenant_id)

    # Filtro por estado
    if estado and estado.upper() != "TODOS":
        query = query.filter(Paciente.estado == estado.upper())

    # Filtro por CI específico
    if ci and ci.strip():
        query = query.filter(Paciente.ci.ilike(f"%{ci.strip()}%"))

    # Filtro por búsqueda general (nombres, apellidos, correo)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Paciente.nombres.ilike(term),
                Paciente.apellidos.ilike(term),
                Paciente.correo.ilike(term),
                Paciente.ci.ilike(term)
            )
        )

    total = query.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 1

    offset = (page - 1) * page_size
    items = query.order_by(Paciente.created_at.desc()).offset(offset).limit(page_size).all()

    return items, total, total_pages


def create_patient(db: Session, data: PacienteCreateRequest, current_tenant_id: Optional[int] = None) -> Paciente:
    """Crea y persiste un nuevo paciente en la base de datos."""
    target_clinica = current_tenant_id if current_tenant_id is not None else data.id_clinica
    db_paciente = Paciente(
        id_clinica=target_clinica,
        id_usuario=data.id_usuario,
        nombres=data.nombres.strip(),
        apellidos=data.apellidos.strip(),
        ci=data.ci.strip(),
        complemento=(data.complemento or "").strip(),
        fecha_nacimiento=data.fecha_nacimiento,
        genero=data.genero.strip().upper(),
        telefono=data.telefono.strip(),
        correo=data.correo.strip().lower() if data.correo else None,
        direccion=data.direccion.strip() if data.direccion else None,
        ciudad=(data.ciudad or "Santa Cruz de la Sierra").strip(),
        tipo_sangre=data.tipo_sangre.strip().upper() if data.tipo_sangre else None,
        alergias=data.alergias.strip() if data.alergias else None,
        antecedentes_patologicos=data.antecedentes_patologicos.strip() if data.antecedentes_patologicos else None,
        contacto_emergencia_nombre=data.contacto_emergencia_nombre.strip() if data.contacto_emergencia_nombre else None,
        contacto_emergencia_telefono=data.contacto_emergencia_telefono.strip() if data.contacto_emergencia_telefono else None,
        contacto_emergencia_parentesco=data.contacto_emergencia_parentesco.strip() if data.contacto_emergencia_parentesco else None,
        seguro_medico=data.seguro_medico.strip() if data.seguro_medico else None,
        numero_seguro=data.numero_seguro.strip() if data.numero_seguro else None,
        estado="ACTIVO"
    )
    db.add(db_paciente)
    db.commit()
    db.refresh(db_paciente)
    return db_paciente


def update_patient(db: Session, id_paciente: int, data: PacienteUpdateRequest, current_tenant_id: Optional[int] = None) -> Optional[Paciente]:
    """Actualiza la información de un paciente existente."""
    paciente = get_patient_by_id(db, id_paciente, current_tenant_id)
    if not paciente:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            if isinstance(value, str):
                setattr(paciente, field, value.strip())
            else:
                setattr(paciente, field, value)

    db.commit()
    db.refresh(paciente)
    return paciente


def patch_patient_profile(db: Session, id_usuario: int, data: PacienteProfilePatchRequest, current_tenant_id: Optional[int] = None) -> Optional[Paciente]:
    """Actualiza los datos de contacto y emergencia propios del paciente autenticado."""
    paciente = get_patient_by_user_id(db, id_usuario, current_tenant_id)
    if not paciente:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            if isinstance(value, str):
                setattr(paciente, field, value.strip())
            else:
                setattr(paciente, field, value)

    db.commit()
    db.refresh(paciente)
    return paciente


def soft_delete_patient(db: Session, id_paciente: int, current_tenant_id: Optional[int] = None) -> Optional[Paciente]:
    """Desactiva lógicamente a un paciente (estado = 'INACTIVO')."""
    paciente = get_patient_by_id(db, id_paciente, current_tenant_id)
    if not paciente:
        return None

    paciente.estado = "INACTIVO"
    db.commit()
    db.refresh(paciente)
    return paciente
