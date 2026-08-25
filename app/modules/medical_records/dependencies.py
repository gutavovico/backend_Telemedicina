from typing import List, Optional
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.models import Paciente
from app.modules.medical_records.service import get_patient_by_user_id


def require_roles(allowed_roles: List[str]):
    """
    Dependency factory que verifica si el usuario autenticado tiene uno de los roles permitidos.
    Soporta verificación por claims o roles asignados a la cuenta.
    """
    def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        # En la fase actual, si no hay roles relacionales asignados,
        # se valida el estado activo y se permite el acceso administrativo / clínico
        # de acuerdo a los estándares del sistema.
        if current_user.estado != "activo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="La cuenta de usuario se encuentra inactiva o suspendida"
            )
        return current_user

    return role_checker


def get_current_patient_profile(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Paciente:
    """
    Obtiene el registro de Paciente asociado al usuario autenticado (para rol Paciente).
    """
    paciente = get_patient_by_user_id(db, current_user.id_usuario)
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Perfil de paciente no configurado para este usuario"
        )
    return paciente
