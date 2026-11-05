from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TenantRequestItem(BaseModel):
    id_request: str
    institucion_nombre: str
    razon_social: Optional[str] = None
    nit: str
    correo: str
    telefono: Optional[str] = None
    responsable_nombre: str
    responsable_correo: str
    id_version_plan: Optional[int] = None
    plan_version_id: Optional[str] = None
    tracking_code: str
    status: str
    decision_motivo: Optional[str] = None
    decision_fecha: Optional[datetime] = None
    row_version: int
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)


class TenantRequestDetail(TenantRequestItem):
    direccion: Optional[str] = None
    responsable_telefono: Optional[str] = None
    documentos_metadata: Optional[str] = None
    tenant_id: Optional[str] = None
    id_clinica: Optional[int] = None


class TenantRequestListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[TenantRequestItem]


class ApproveRequest(BaseModel):
    row_version: int = Field(default=1)


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=3)
    row_version: int = Field(default=1)


class TenantItem(BaseModel):
    id_clinica: int
    tenant_id: Optional[str] = None
    nombre: str
    razon_social: Optional[str] = None
    nit: Optional[str] = None
    correo: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    estado: str
    id_version_plan: Optional[int] = None
    plan_id: Optional[str] = None
    commercial_notes: Optional[str] = None
    row_version: int
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)


TenantDetail = TenantItem


class TenantListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[TenantItem]


class TenantStateAction(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    row_version: int = Field(..., ge=1)


class CommercialAgreementUpdate(BaseModel):
    plan_id: Optional[int] = None
    commercial_notes: Optional[str] = None
    row_version: int = Field(default=1)


class TenantContextResponse(BaseModel):
    clinica_id: Optional[int] = None
    clinica_nombre: str = ""
    clinica_estado: Optional[str] = None
    usuario_id: int
    usuario_nombres: str
    usuario_apellidos: str
    usuario_correo: str
    rol: str = ""
    permisos: List[str] = []
    es_super_admin: bool = False

