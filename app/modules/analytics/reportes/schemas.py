"""Strict request and response shapes shared by web and mobile clients."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from .catalog import MAX_COLUMNS, MAX_FILTERS, MAX_GROUPS, MAX_PAGE_SIZE, MAX_PERIOD_DAYS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Period(StrictModel):
    desde: date
    hasta: date

    @model_validator(mode="after")
    def valid_range(self):
        span = (self.hasta - self.desde).days + 1
        if not 1 <= span <= MAX_PERIOD_DAYS:
            raise ValueError(f"El período debe contener entre 1 y {MAX_PERIOD_DAYS} días")
        return self


class Filter(StrictModel):
    campo: StrictStr
    operador: Literal["eq"]
    valor: StrictInt | StrictStr


class Sort(StrictModel):
    campo: StrictStr
    direccion: Literal["asc", "desc"]


class QueryRequest(StrictModel):
    reporte: StrictStr
    periodo: Period
    filtros: list[Filter] = Field(default_factory=list, max_length=MAX_FILTERS)
    columnas: list[StrictStr] = Field(default_factory=list, max_length=MAX_COLUMNS)
    agrupacion: list[StrictStr] = Field(default_factory=list, max_length=MAX_GROUPS)
    orden: list[Sort] = Field(default_factory=list, max_length=MAX_COLUMNS)
    pagina: StrictInt = Field(1, ge=1)
    tamano_pagina: StrictInt = Field(20, ge=1, le=MAX_PAGE_SIZE)


class Metric(BaseModel):
    disponible: bool
    valor: int | None
    causa: str | None = None


class QueryResponse(BaseModel):
    definicion: QueryRequest
    semantica: str
    metricas: dict[str, Metric]
    total: int
    filas: list[dict[str, str | int | None]]
    advertencias: list[str]
    generado_en: datetime
