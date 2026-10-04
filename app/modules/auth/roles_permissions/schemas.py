from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class RoleBase(BaseModel):
    id_clinica: Optional[int] = Field(None, gt=0)
    tenant_id: Optional[str] = None
    nombre: str = Field(..., min_length=2, max_length=100)
    descripcion: Optional[str] = None


class RoleCreate(RoleBase):
    estado: str = Field(default="ACTIVO", min_length=1, max_length=20)


class RoleUpdate(BaseModel):
    id_clinica: Optional[int] = Field(None, gt=0)
    tenant_id: Optional[str] = None
    nombre: Optional[str] = Field(None, min_length=2, max_length=100)
    descripcion: Optional[str] = None
    estado: Optional[str] = Field(None, min_length=1, max_length=20)


class RoleStatusUpdate(BaseModel):
    activo: bool


class RoleResponse(BaseModel):
    id_rol: int
    id_clinica: Optional[int] = None
    tenant_id: Optional[str] = None
    nombre: str
    descripcion: Optional[str] = None
    estado: str

    model_config = ConfigDict(from_attributes=True)


class PermissionResponse(BaseModel):
    id_permiso: int
    codigo: Optional[str] = None
    nombre: str
    descripcion: Optional[str] = None
    modulo: str
    accion: Optional[str] = None
    estado: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RolePermissionsUpdate(BaseModel):
    id_permisos: List[int] = Field(default_factory=list)
