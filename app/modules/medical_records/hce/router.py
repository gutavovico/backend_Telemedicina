from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import (
    get_current_tenant_id,
    get_current_user,
    require_roles,
)
from app.modules.auth.models import Usuario
from app.modules.appointments.models import Medico
from app.modules.medical_records.hce import schemas, service as hce_service
from app.modules.medical_records.hce.dependencies import get_current_medico_profile
from app.modules.medical_records.patient_profile.service import get_patient_by_user_id


router = APIRouter(prefix="/api/v1/hce", tags=["Historia Clínica Electrónica (CU28)"])


@router.get(
    "/pacientes/{id_paciente}",
    response_model=schemas.HistoriaClinicaCompletaResponse,
    summary="Obtener historia clínica consolidada del paciente",
    description="Permite a médicos, administradores y al propio paciente consultar el expediente consolidado en el tenant.",
)
def obtener_historia_clinica(
    id_paciente: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["MEDICO", "ADMIN", "PACIENTE"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    """Obtiene el expediente completo del paciente validando permisos por rol y aislamiento multitenant."""
    rol_nombre = current_user.rol.nombre.upper() if current_user.rol else ""
    if rol_nombre == "PACIENTE" or current_user.id_rol == 4:
        perfil = get_patient_by_user_id(db, current_user.id_usuario, tenant_id=tenant_id)
        if not perfil or perfil.id_paciente != id_paciente:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para consultar el expediente de otro paciente",
            )

    return hce_service.get_or_create_historia_by_paciente(db, id_paciente, tenant_id=tenant_id)


@router.post(
    "/pacientes/{id_paciente}/consultas",
    response_model=schemas.ConsultaResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nueva consulta médica estructurada",
    description="Permite al médico tratante registrar la consulta con notas SOAP, signos vitales y diagnósticos CIE-10.",
)
def registrar_nueva_consulta(
    id_paciente: int,
    request_data: schemas.ConsultaCreateRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["MEDICO"])),
    medico: Medico = Depends(get_current_medico_profile),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    """Registra una nueva consulta médica con diagnósticos CIE-10 y finaliza la cita."""
    ip_cliente = req.client.host if req.client else "0.0.0.0"
    return hce_service.registrar_consulta_clinica(
        db=db,
        id_paciente=id_paciente,
        payload=request_data,
        medico_usuario=current_user,
        medico=medico,
        ip_cliente=ip_cliente,
        tenant_id=tenant_id,
    )


@router.get(
    "/consultas/{id_consulta}",
    response_model=schemas.ConsultaResponseSchema,
    summary="Obtener detalle de una consulta clínica",
    description="Obtiene el detalle clínico de una consulta y sus diagnósticos CIE-10 asociados.",
)
def detalle_de_consulta(
    id_consulta: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["MEDICO", "ADMIN", "PACIENTE"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    """Obtiene el detalle de una consulta validando reglas de negocio multitenant."""
    return hce_service.get_consulta_by_id(db, id_consulta, current_user, tenant_id=tenant_id)
