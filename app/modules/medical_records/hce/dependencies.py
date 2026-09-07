from typing import Optional
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, get_current_tenant_id
from app.modules.auth.models import Usuario
from app.modules.appointments.models import Medico
from app.modules.appointments.doctor_profile.service import obtener_medico_por_usuario


def get_current_medico_profile(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
) -> Medico:
    """Obtiene el perfil de medico vinculado al usuario autenticado en el tenant actual."""
    return obtener_medico_por_usuario(db, current_user.id_usuario, current_tenant_id=tenant_id)
