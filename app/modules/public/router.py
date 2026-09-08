from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.public.schemas import (
    AdminSummary,
    ClinicaRegistroRequest,
    ClinicaRegistroResponse,
    ClinicaSummary,
)
from app.modules.public.service import registrar_clinica

router = APIRouter(prefix="/public", tags=["Público / Onboarding"])


@router.post(
    "/clinicas/registrar",
    response_model=ClinicaRegistroResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_registrar_clinica(
    payload: ClinicaRegistroRequest,
    db: Session = Depends(get_db),
):
    """
    Public onboarding endpoint to register a new clinic and its administrator account.
    """
    clinica, admin_user = registrar_clinica(db, data=payload)
    return ClinicaRegistroResponse(
        clinica=ClinicaSummary(
            id_clinica=clinica.id_clinica,
            nombre=clinica.nombre,
            estado=clinica.estado,
        ),
        administrador=AdminSummary(
            id_usuario=admin_user.id_usuario,
            correo=admin_user.correo,
        ),
    )
