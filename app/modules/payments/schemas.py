"""Esquemas Pydantic v2 para CU19 - Pagos y comprobantes."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class PagoBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckoutCreate(PagoBase):
    id_cita: int = Field(..., gt=0, description="Cita o teleconsulta a pagar")
    canal: Literal["WEB", "MOVIL"] = Field(
        "WEB", description="Canal que inicia el pago; define las URLs de retorno"
    )
    metodo_pago: Literal["TARJETA", "QR"] = Field(
        "TARJETA", description="Método elegido por el paciente"
    )


class ComprobanteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_comprobante: int
    id_pago: int
    numero_comprobante: str
    tipo_comprobante: str
    fecha_emision: Optional[datetime] = None
    archivo_url: Optional[str] = None
    estado: str


class PagoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_pago: int
    id_usuario: int
    id_cita: Optional[int] = None
    monto: Decimal
    moneda: str
    metodo_pago: Optional[str] = None
    pasarela: Optional[str] = None
    referencia_transaccion: Optional[str] = None
    fecha_pago: Optional[datetime] = None
    estado: str
    url_checkout: Optional[str] = None
    expira_en: Optional[datetime] = None
    created_at: Optional[datetime] = None

    # Datos descriptivos de la cita
    cita_fecha: Optional[date] = None
    cita_hora: Optional[str] = None
    medico_nombre: Optional[str] = None
    especialidad_nombre: Optional[str] = None
    tipo_consulta: Optional[str] = None

    comprobante: Optional[ComprobanteResponse] = None


class CheckoutResponse(PagoResponse):
    qr_url: Optional[str] = None
    qr_payload: Optional[str] = None
    simulado: bool = False


class PagoListResponse(BaseModel):
    total: int
    items: List[PagoResponse]


class CitaPendientePago(BaseModel):
    id_cita: int
    fecha_cita: Optional[date] = None
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    medico_nombre: Optional[str] = None
    especialidad_nombre: Optional[str] = None
    tipo_consulta: Optional[str] = None
    estado_cita: Optional[str] = None
    monto: Decimal
    moneda: str
    estado_pago: Optional[str] = None
    id_pago: Optional[int] = None


class CitaPendienteListResponse(BaseModel):
    total: int
    items: List[CitaPendientePago]
