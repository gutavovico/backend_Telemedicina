from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class DeactivationRequestCreate(BaseModel):
    motivo: str = Field(..., min_length=5, max_length=1000, description="Motivo formal de la solicitud de baja")


class DeactivationResponse(BaseModel):
    id_deactivation: str
    status: str
    message: str

    model_config = ConfigDict(from_attributes=True)


class DeactivationDecisionRequest(BaseModel):
    row_version: int = Field(..., ge=1)
    motivo: Optional[str] = Field(None, max_length=1000)


class DeactivationRequestItem(BaseModel):
    id_deactivation: str
    id_clinica: int
    tenant_id: Optional[str] = None
    institucion: str
    motivo: str
    status: str
    row_version: int
    decision_motivo: Optional[str] = None
    decision_fecha: Optional[datetime] = None
    fecha_creacion: datetime


class DeactivationListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[DeactivationRequestItem]

