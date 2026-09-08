from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class TenantContextResponse(BaseModel):
    clinica_id: Optional[int] = None
    clinica_nombre: str = ""
    clinica_estado: Optional[str] = None
    usuario_id: int
    usuario_nombres: str
    usuario_apellidos: str
    usuario_correo: str
    rol: str
    permisos: List[str] = []
    es_super_admin: bool = False

    model_config = ConfigDict(from_attributes=True)
