from datetime import datetime
from typing import List, Optional, Literal
from decimal import Decimal
from pydantic import field_serializer
from app.modules.auth.planes.schemas import VersionResponse
from pydantic import BaseModel, ConfigDict, Field


class CurrentSubscriptionResponse(BaseModel):
    has_subscription: bool
    id_suscripcion: Optional[str] = None
    tenant_id: Optional[str] = None
    plan_nombre: Optional[str] = None
    id_plan_version: Optional[int] = None
    plan_version_id: Optional[int] = None
    version: Optional[VersionResponse] = None
    row_version: Optional[int] = None
    ciclo: Optional[str] = None
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    dias_gracia: Optional[int] = None
    estado: Optional[str] = None
    derived_status: Optional[str] = None
    limite_medicos: Optional[int] = None
    limite_consultas_mes: Optional[int] = None
    limite_sedes: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class PlanVersionItem(VersionResponse):
    id_plan_version: int
    limite_consultas_mes: Optional[int] = None


class CreateCheckoutRequest(BaseModel):
    plan_version_id: int = Field(strict=True, gt=0)
    cycle: Literal["MONTHLY", "MENSUAL"] = "MONTHLY"

    model_config = ConfigDict(extra="forbid")


class CheckoutResponse(BaseModel):
    id_pago: str
    monto: Decimal
    moneda: str
    checkout_url: str
    expira_en: Optional[datetime] = None


class CheckoutStatusResponse(BaseModel):
    id_pago: str
    estado: str
    confirmado: bool
    application_status: str
    effective_at: Optional[datetime] = None
    application_reason: Optional[str] = None
    checkout_url: Optional[str] = None
    expira_en: Optional[datetime] = None


class SubscriptionPaymentItem(BaseModel):
    application_status: str
    application_reason: Optional[str] = None
    plan_version_id: int
    version: VersionResponse
    purpose: Literal["RENEWAL", "UPGRADE"]
    id_pago: str
    monto: Decimal
    moneda: str
    ciclo: str
    estado: str
    plan_nombre: Optional[str] = None
    numero_factura: Optional[str] = None
    fecha_pago: Optional[datetime] = None
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)


class SubscriptionPaymentHistoryResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[SubscriptionPaymentItem]


class ReceiptMetadataResponse(BaseModel):
    plan_version_id: int
    purpose: Literal["RENEWAL", "UPGRADE"]
    id_pago: str
    numero_factura: str
    monto: Decimal
    moneda: str
    fecha_pago: Optional[datetime] = None
    tenant_nombre: str
    plan_nombre: str
    ciclo: str
    stripe_referencia: Optional[str] = None

