from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records import service
from app.modules.medical_records.dependencies import require_roles
from app.modules.medical_records.schemas import (
    PacienteCreateRequest,
    PacienteUpdateRequest,
    PacienteProfilePatchRequest,
    PacienteResponse,
    PacientePaginationResponse
)

router = APIRouter(prefix="/api/v1/pacientes", tags=["Pacientes"])


@router.post(
    "",
    response_model=PacienteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un nuevo paciente",
    description="Permite al personal autorizado (Recepción / Admin) dar de alta un paciente con su expediente base."
)
def create_patient_endpoint(
    data: PacienteCreateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN", "RECEPCION"]))
):
    # Verificar si el carnet de identidad ya existe
    existente = service.get_patient_by_ci(db, data.ci, data.complemento)
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un paciente registrado con el documento de identidad ingresado"
        )

    try:
        paciente = service.create_patient(db, data)
        return paciente
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto de integridad: documento o cuenta ya asociada a otro paciente."
        )


@router.get(
    "",
    response_model=PacientePaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar pacientes con filtros y paginación",
    description="Obtiene una lista paginada de pacientes con soporte de búsqueda por C.I., nombres o apellidos."
)
def list_patients_endpoint(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(10, ge=1, le=100, description="Cantidad de registros por página"),
    q: Optional[str] = Query(None, description="Búsqueda por nombres, apellidos, correo o C.I."),
    ci: Optional[str] = Query(None, description="Búsqueda exacta/parcial por C.I."),
    estado: Optional[str] = Query("ACTIVO", description="Filtro por estado ('ACTIVO', 'INACTIVO', 'TODOS')"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN", "RECEPCION", "MEDICO"]))
):
    items, total, total_pages = service.list_patients(
        db, page=page, page_size=page_size, q=q, ci=ci, estado=estado
    )
    return PacientePaginationResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get(
    "/me",
    response_model=PacienteResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener perfil del paciente autenticado",
    description="Permite al paciente autenticado (App Móvil / Web) obtener sus datos personales y clínicos base."
)
def get_my_patient_profile(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    paciente = service.get_patient_by_user_id(db, current_user.id_usuario)
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Perfil de paciente no configurado para este usuario"
        )
    return paciente


@router.patch(
    "/me",
    response_model=PacienteResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar perfil propio del paciente",
    description="Permite al paciente autenticado actualizar sus datos de contacto y emergencia desde la app móvil o web."
)
def patch_my_patient_profile(
    data: PacienteProfilePatchRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    paciente = service.patch_patient_profile(db, current_user.id_usuario, data)
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Perfil de paciente no encontrado para este usuario"
        )
    return paciente


@router.get(
    "/{id_paciente}",
    response_model=PacienteResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle de un paciente por ID",
    description="Permite a médicos y administradores consultar el expediente completo de un paciente."
)
def get_patient_detail(
    id_paciente: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN", "RECEPCION", "MEDICO"]))
):
    paciente = service.get_patient_by_id(db, id_paciente)
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paciente no encontrado"
        )
    return paciente


@router.put(
    "/{id_paciente}",
    response_model=PacienteResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar expediente de un paciente",
    description="Permite al personal médico o administrativo actualizar datos generales, de contacto o clínicos base."
)
def update_patient_endpoint(
    id_paciente: int,
    data: PacienteUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN", "RECEPCION", "MEDICO"]))
):
    paciente = service.update_patient(db, id_paciente, data)
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paciente no encontrado"
        )
    return paciente


@router.delete(
    "/{id_paciente}",
    status_code=status.HTTP_200_OK,
    summary="Desactivar paciente (Baja lógica)",
    description="Realiza el borrado lógico del paciente cambiando su estado a 'INACTIVO'."
)
def delete_patient_endpoint(
    id_paciente: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN"]))
):
    paciente = service.soft_delete_patient(db, id_paciente)
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paciente no encontrado"
        )
    return {
        "detail": "Paciente desactivado correctamente",
        "id_paciente": id_paciente,
        "estado": "INACTIVO"
    }
