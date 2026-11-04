from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CurrentSubscriptionResponse(BaseModel):
    has_subscription: bool
    id_suscripcion: Optional[str] = None
    tenant_id: Optional[str] = None
    plan_nombre: Optional[str] = None
    plan_version_id: Optional[str] = None
    ciclo: Optional[str] = None
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    dias_gracia: Optional[int] = None
    estado: Optional[str] = None
    derived_status: Optional[str] = None
    limite_medicos: Optional[int] = None
    limite_consultas_mes: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class PlanVersionItem(BaseModel):
    id_plan_version: str
    nombre: str
    descripcion: Optional[str] = None
    precio_mensual: float
    precio_anual: float
    moneda: str
    limite_medicos: int
    limite_consultas_mes: int

    model_config = ConfigDict(from_attributes=True)


class CreateCheckoutRequest(BaseModel):
    plan_version_id: str
    cycle: str = Field(..., pattern="^(MONTHLY|ANNUAL)$")

    model_config = ConfigDict(extra="forbid")


class CheckoutResponse(BaseModel):
    id_pago: str
    monto: float
    moneda: str
    checkout_url: str
    expira_en: Optional[datetime] = None


class CheckoutStatusResponse(BaseModel):
    id_pago: str
    estado: str
    confirmado: bool
    checkout_url: Optional[str] = None
    expira_en: Optional[datetime] = None


class SubscriptionPaymentItem(BaseModel):
    id_pago: str
    monto: float
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
    id_pago: str
    numero_factura: str
    monto: float
    moneda: str
    fecha_pago: Optional[datetime] = None
    tenant_nombre: str
    plan_nombre: str
    ciclo: str
    stripe_referencia: Optional[str] = None

