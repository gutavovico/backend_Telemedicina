"""CU22 interpretation contract; it never includes report rows or tenant identifiers."""

from datetime import date
from typing import Literal

from pydantic import Field, StrictStr, field_validator

from .schemas import QueryRequest, StrictModel


InterpretState = Literal["valida", "aclaracion", "no_admitida"]
ClarificationField = Literal[
    "reporte", "periodo", "id_medico", "id_especialidad", "filtros",
    "agrupacion", "columnas", "orden",
]


class InterpretRequest(StrictModel):
    texto: StrictStr = Field(min_length=1, max_length=1000)
    fecha_referencia: date | None = None

    @field_validator("texto")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("El texto debe contener una solicitud legible")
        return value.strip()


class InterpretResponse(StrictModel):
    estado: InterpretState
    definicion: QueryRequest | None
    resumen: str
    campos_aclaracion: list[ClarificationField]
    advertencias: list[str]


class ProposedFilter(StrictModel):
    campo: StrictStr = Field(max_length=40)
    valor: StrictStr = Field(max_length=100)


class ProposedPeriod(StrictModel):
    desde: StrictStr = Field(max_length=10)
    hasta: StrictStr = Field(max_length=10)


class ProposedSort(StrictModel):
    campo: StrictStr = Field(max_length=40)
    direccion: StrictStr = Field(max_length=4)


class ProposedInterpretation(StrictModel):
    estado: InterpretState
    reporte: StrictStr = Field(max_length=40)
    periodo: ProposedPeriod
    filtros: list[ProposedFilter] = Field(max_length=8)
    agrupacion: list[StrictStr] = Field(max_length=2)
    columnas: list[StrictStr] = Field(max_length=6)
    orden: list[ProposedSort] = Field(max_length=6)
    campos_aclaracion: list[ClarificationField] = Field(max_length=8)
