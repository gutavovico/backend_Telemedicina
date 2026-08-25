from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.modules.auth.models import Usuario
from app.modules.medicos.models import Especialidad, Medico, MedicoEspecialidad
from app.modules.medicos.schemas import (
    AsignacionEspecialidad,
    EspecialidadCreate,
    EspecialidadUpdate,
    MedicoCreate,
    MedicoUpdate,
)

ESTADOS_VALIDOS = ("activo", "inactivo")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_especialidades_por_ids(db: Session, ids: List[int]) -> List[Especialidad]:
    """Valida que todos los ids de especialidad existan y estén activos."""
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La lista de especialidades contiene ids duplicados",
        )
    encontradas = db.query(Especialidad).filter(Especialidad.id_especialidad.in_(ids)).all()
    if len(encontradas) != len(set(ids)):
        faltantes = set(ids) - {e.id_especialidad for e in encontradas}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Especialidades no encontradas: {sorted(faltantes)}",
        )
    inactivas = [e.nombre for e in encontradas if e.estado != "activo"]
    if inactivas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Especialidades inactivas: {inactivas}",
        )
    return encontradas


def _cargar_relaciones(query):
    return query.options(
        joinedload(Medico.usuario),
        joinedload(Medico.especialidades).joinedload(MedicoEspecialidad.especialidad),
    )


# ---------------------------------------------------------------------------
# Médicos
# ---------------------------------------------------------------------------

def crear_medico(db: Session, medico_data: MedicoCreate) -> Medico:
    """Crea el perfil profesional de un usuario existente (regla 1:1)."""
    usuario = db.query(Usuario).filter(Usuario.id_usuario == medico_data.id_usuario).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con id {medico_data.id_usuario} no encontrado",
        )
    if usuario.estado != "activo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El usuario está inactivo o suspendido; no puede tener perfil médico",
        )

    existente = db.query(Medico).filter(Medico.id_usuario == medico_data.id_usuario).first()
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El usuario ya tiene un perfil médico asociado (relación 1:1)",
        )

    matricula_duplicada = (
        db.query(Medico)
        .filter(Medico.matricula_profesional == medico_data.matricula_profesional)
        .first()
    )
    if matricula_duplicada:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La matrícula '{medico_data.matricula_profesional}' ya está registrada",
        )

    especialidades: List[Especialidad] = []
    if medico_data.especialidades:
        especialidades = _get_especialidades_por_ids(db, medico_data.especialidades)

    nuevo_medico = Medico(
        id_usuario=medico_data.id_usuario,
        matricula_profesional=medico_data.matricula_profesional,
        descripcion_profesional=medico_data.descripcion_profesional,
        experiencia=medico_data.experiencia,
        foto_perfil=medico_data.foto_perfil,
        estado="activo",
    )

    # La primera especialidad de la lista queda como principal
    for idx, esp in enumerate(especialidades):
        nuevo_medico.especialidades.append(
            MedicoEspecialidad(
                id_especialidad=esp.id_especialidad,
                es_principal=(idx == 0),
            )
        )

    db.add(nuevo_medico)
    db.commit()
    db.refresh(nuevo_medico)
    return nuevo_medico


def listar_medicos(
    db: Session,
    nombre: Optional[str] = None,
    id_especialidad: Optional[int] = None,
    estado: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[int, List[Medico]]:
    """Lista médicos con filtros y paginación. Devuelve (total, items)."""
    query = db.query(Medico)

    if estado is not None:
        query = query.filter(Medico.estado == estado)
    else:
        query = query.filter(Medico.estado == "activo")

    if nombre:
        query = query.join(Usuario).filter(
            (Usuario.nombres.ilike(f"%{nombre}%"))
            | (Usuario.apellidos.ilike(f"%{nombre}%"))
            | (Usuario.correo.ilike(f"%{nombre}%"))
        )

    if id_especialidad is not None:
        query = query.join(MedicoEspecialidad).filter(
            MedicoEspecialidad.id_especialidad == id_especialidad
        )

    query = query.distinct()
    total = query.count()
    items = (
        _cargar_relaciones(query)
        .order_by(Medico.id_medico)
        .offset(skip)
        .limit(limit)
        .all()
    )
    return total, items


def obtener_medico(db: Session, id_medico: int) -> Medico:
    medico = (
        _cargar_relaciones(db.query(Medico))
        .filter(Medico.id_medico == id_medico)
        .first()
    )
    if not medico:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Médico con id {id_medico} no encontrado",
        )
    return medico


def obtener_medico_por_usuario(db: Session, id_usuario: int) -> Medico:
    medico = (
        _cargar_relaciones(db.query(Medico))
        .filter(Medico.id_usuario == id_usuario)
        .first()
    )
    if not medico:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario autenticado no tiene perfil médico asociado",
        )
    return medico


def actualizar_medico(db: Session, id_medico: int, datos: MedicoUpdate) -> Medico:
    medico = obtener_medico(db, id_medico)

    if datos.matricula_profesional and datos.matricula_profesional != medico.matricula_profesional:
        duplicada = (
            db.query(Medico)
            .filter(
                Medico.matricula_profesional == datos.matricula_profesional,
                Medico.id_medico != id_medico,
            )
            .first()
        )
        if duplicada:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La matrícula '{datos.matricula_profesional}' ya está registrada",
            )

    cambios = datos.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(medico, campo, valor)

    db.commit()
    db.refresh(medico)
    return medico


def cambiar_estado_medico(db: Session, id_medico: int, nuevo_estado: str) -> Medico:
    medico = obtener_medico(db, id_medico)
    medico.estado = nuevo_estado
    db.commit()
    db.refresh(medico)
    return medico


# ---------------------------------------------------------------------------
# Especialidades de un médico
# ---------------------------------------------------------------------------

def asignar_especialidad(db: Session, id_medico: int, asignacion: AsignacionEspecialidad) -> Medico:
    medico = obtener_medico(db, id_medico)

    especialidad = (
        db.query(Especialidad)
        .filter(Especialidad.id_especialidad == asignacion.id_especialidad)
        .first()
    )
    if not especialidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Especialidad con id {asignacion.id_especialidad} no encontrada",
        )
    if especialidad.estado != "activo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La especialidad '{especialidad.nombre}' está inactiva",
        )

    ya_asignada = (
        db.query(MedicoEspecialidad)
        .filter(
            MedicoEspecialidad.id_medico == id_medico,
            MedicoEspecialidad.id_especialidad == asignacion.id_especialidad,
        )
        .first()
    )
    if ya_asignada:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El médico ya tiene asignada la especialidad '{especialidad.nombre}'",
        )

    # Regla: solo una especialidad principal por médico
    if asignacion.es_principal:
        db.query(MedicoEspecialidad).filter(
            MedicoEspecialidad.id_medico == id_medico,
            MedicoEspecialidad.es_principal.is_(True),
        ).update({"es_principal": False}, synchronize_session=False)

    medico.especialidades.append(
        MedicoEspecialidad(
            id_especialidad=asignacion.id_especialidad,
            es_principal=asignacion.es_principal,
        )
    )
    db.commit()
    db.refresh(medico)
    return medico


def quitar_especialidad(db: Session, id_medico: int, id_especialidad: int) -> Medico:
    medico = obtener_medico(db, id_medico)
    asociacion = (
        db.query(MedicoEspecialidad)
        .filter(
            MedicoEspecialidad.id_medico == id_medico,
            MedicoEspecialidad.id_especialidad == id_especialidad,
        )
        .first()
    )
    if not asociacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El médico no tiene asignada esa especialidad",
        )

    db.delete(asociacion)
    db.commit()
    db.refresh(medico)
    return medico


# ---------------------------------------------------------------------------
# Catálogo de especialidades
# ---------------------------------------------------------------------------

def listar_especialidades(db: Session, solo_activas: bool = True) -> List[Especialidad]:
    query = db.query(Especialidad)
    if solo_activas:
        query = query.filter(Especialidad.estado == "activo")
    return query.order_by(Especialidad.nombre).all()


def crear_especialidad(db: Session, datos: EspecialidadCreate) -> Especialidad:
    existente = (
        db.query(Especialidad).filter(Especialidad.nombre.ilike(datos.nombre.strip())).first()
    )
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La especialidad '{datos.nombre}' ya existe",
        )
    nueva = Especialidad(
        nombre=datos.nombre.strip(),
        descripcion=datos.descripcion,
        estado="activo",
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva


def actualizar_especialidad(db: Session, id_especialidad: int, datos: EspecialidadUpdate) -> Especialidad:
    especialidad = db.query(Especialidad).filter(Especialidad.id_especialidad == id_especialidad).first()
    if not especialidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Especialidad con id {id_especialidad} no encontrada",
        )

    cambios = datos.model_dump(exclude_unset=True)
    if "nombre" in cambios and cambios["nombre"]:
        duplicada = (
            db.query(Especialidad)
            .filter(
                Especialidad.nombre.ilike(cambios["nombre"].strip()),
                Especialidad.id_especialidad != id_especialidad,
            )
            .first()
        )
        if duplicada:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La especialidad '{cambios['nombre']}' ya existe",
            )

    for campo, valor in cambios.items():
        setattr(especialidad, campo, valor)

    db.commit()
    db.refresh(especialidad)
    return especialidad


def eliminar_especialidad(db: Session, id_especialidad: int) -> None:
    especialidad = db.query(Especialidad).filter(Especialidad.id_especialidad == id_especialidad).first()
    if not especialidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Especialidad con id {id_especialidad} no encontrada",
        )

    asignaciones = (
        db.query(MedicoEspecialidad)
        .filter(MedicoEspecialidad.id_especialidad == id_especialidad)
        .count()
    )
    if asignaciones > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se puede eliminar: {asignaciones} médico(s) tienen asignada esta especialidad",
        )

    db.delete(especialidad)
    db.commit()
