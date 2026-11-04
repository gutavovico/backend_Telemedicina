"""Contrato CU34: importes decimales en texto y condiciones inmutables."""
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, field_serializer, field_validator, model_validator

SERVICIOS = {
    "AGENDA_TELECONSULTA": "Agenda y teleconsulta",
    "RECETAS_DIGITALES": "Recetas digitales",
    "LABORATORIO": "Laboratorio",
    "LISTA_ESPERA": "Lista de espera",
    "REPORTES_AUDITORIA": "Reportes y auditoría",
    "TRIAJE_IA": "Triaje con IA",
    "SUBDOMINIO_PROPIO": "Subdominio propio",
    "INTEGRACIONES": "Integraciones",
}
RECURSOS = {
    "MEDICOS": ("MEDICO_CICLO_MENSUAL", "Médico por ciclo mensual", "limite_medicos"),
    "SEDES": ("SEDE_CICLO_MENSUAL", "Sede por ciclo mensual", "limite_sedes"),
    "CONSULTAS": ("CONSULTA", "Consulta", "limite_consultas"),
}


def _money(value):
    if isinstance(value, Decimal):
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", value):
        raise ValueError("Use un importe decimal no negativo con hasta dos decimales, como texto")
    return Decimal(value)


Money = Annotated[Decimal, BeforeValidator(_money), Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
Count = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Tarifa(Schema):
    recurso: Literal["MEDICOS", "SEDES", "CONSULTAS"]
    unidad: Literal["MEDICO_CICLO_MENSUAL", "SEDE_CICLO_MENSUAL", "CONSULTA"]
    precio: Money

    @model_validator(mode="after")
    def unit_matches(self):
        if self.unidad != RECURSOS[self.recurso][0]:
            raise ValueError("La unidad no corresponde al recurso")
        return self

    @field_serializer("precio")
    def serialize_price(self, value: Decimal):
        return format(value, ".2f")


class Condiciones(Schema):
    nombre: str = Field(min_length=1, max_length=150)
    descripcion: str | None = Field(default=None, max_length=2000)
    precio_mensual: Money
    moneda: Literal["BOB"] = "BOB"
    ciclo: Literal["MENSUAL"] = "MENSUAL"
    servicios_incluidos: list[str] = Field(max_length=len(SERVICIOS))
    limite_medicos: Count | None
    limite_sedes: Count | None
    limite_consultas: Count | None
    tarifas_excedentes: list[Tarifa] = Field(default_factory=list, max_length=3)
    demora_pago_dias: Count

    @field_validator("nombre", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("servicios_incluidos")
    @classmethod
    def services_valid(cls, value):
        if len(set(value)) != len(value) or any(code not in SERVICIOS for code in value):
            raise ValueError("Servicios desconocidos o duplicados")
        return value

    @model_validator(mode="after")
    def tariffs_valid(self):
        resources = [t.recurso for t in self.tarifas_excedentes]
        if len(set(resources)) != len(resources):
            raise ValueError("Solo se permite una tarifa por recurso")
        for tariff in self.tarifas_excedentes:
            if getattr(self, RECURSOS[tariff.recurso][2]) is None:
                raise ValueError("Un recurso sin límite no admite tarifa de excedente")
        return self

    @field_serializer("precio_mensual")
    def serialize_price(self, value: Decimal):
        return format(value, ".2f")


class PlanCreate(Condiciones):
    codigo: str = Field(min_length=1, max_length=50, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")

    @field_validator("codigo", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class VersionCreate(Condiciones):
    version_base: Annotated[int, Field(strict=True, ge=1, le=2147483646)]


class Desactivar(Schema):
    activo: Literal[False]

    @field_validator("activo", mode="before")
    @classmethod
    def only_false(cls, value):
        if value is not False:
            raise ValueError("Solo se permite desactivar con activo=false")
        return value


class VersionResponse(Condiciones):
    id: int
    plan_id: int
    numero: int
    creado_en: datetime
    creado_por: int


class PlanResponse(Schema):
    id: int
    codigo: str
    activo: bool
    version_actual: int
    creado_en: datetime
    actualizado_en: datetime
    version: VersionResponse


class PlanPage(Schema):
    items: list[PlanResponse]
    total: int
    page: int
    per_page: int


class VersionPage(Schema):
    items: list[VersionResponse]
    total: int
    page: int
    per_page: int
