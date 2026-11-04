"""CU34 no concede privilegios por IDs fijos ni por coincidencias parciales."""
import unicodedata
from fastapi import Depends, HTTPException
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


def require_catalog_admin(user: Usuario = Depends(get_current_user)) -> Usuario:
    role = user.rol_rel
    name = unicodedata.normalize("NFKD", role.nombre if role else "")
    name = "".join(c for c in name if not unicodedata.combining(c)).upper().strip().replace("_", " ")
    if (user.id_clinica is not None or role is None or role.id_clinica is not None
            or (role.estado or "").upper() != "ACTIVO"
            or (user.estado or "").upper() != "ACTIVO"
            or name not in {"SUPER ADMINISTRADOR", "SUPER ADMIN", "SUPERADMIN"}):
        raise HTTPException(403, "Se requiere superadministrador global")
    return user
