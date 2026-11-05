from fastapi import Depends, HTTPException
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


def require_entity_admin(user: Usuario = Depends(get_current_user)):
    if user.id_clinica is None or str(user.rol or '').strip().upper() not in ('ADMIN','ADMINISTRADOR','ADMINISTRACION'):
        raise HTTPException(403, 'Se requiere el administrador de la entidad')
    return user
