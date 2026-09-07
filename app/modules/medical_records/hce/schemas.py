from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TipoDiagnosticoEnum(str, Enum):
    PRESUNTIVO = "PRESUNTIVO"
    DEFINITIVO = "DEFINITIVO"
    REPETITIVO = "REPETITIVO"


class SignosVitalesSchema(BaseModel):
    frecuencia_cardiaca_lpm: Optional[int] = Field(
        None, ge=30, le=250, description="Latidos por minuto"
    )
    presion_sistolica_mmhg: Optional[int] = Field(None, ge=50, le=260)
    presion_diastolica_mmhg: Optional[int] = Field(None, ge=30, le=160)
    temperatura_corporal_c: Optional[float] = Field(
        None, ge=30.0, le=45.0, description="Grados Celsius"
    )
    saturacion_oxigeno_pct: Optional[int] = Field(
        None, ge=50, le=100, description="Porcentaje de SpO2"
    )
    peso_kg: Optional[float] = Field(None, ge=1.0, le=350.0)
    talla_cm: Optional[float] = Field(None, ge=30.0, le=250.0)
    indice_masa_corporal: Optional[float] = None

    @model_validator(mode="after")
    def calcular_imc(self):
        if self.indice_masa_corporal is None and self.peso_kg and self.talla_cm:
            talla_m = self.talla_cm / 100.0
            self.indice_masa_corporal = round(self.peso_kg / (talla_m ** 2), 2)
        return self


class DiagnosticoCreateSchema(BaseModel):
    codigo_cie: str = Field(..., max_length=30)
    descripcion: str = Field(..., min_length=3)
    tipo: TipoDiagnosticoEnum = TipoDiagnosticoEnum.PRESUNTIVO
    observaciones: Optional[str] = None


class DiagnosticoResponseSchema(DiagnosticoCreateSchema):
    id_diagnostico: int
    fecha_registro: datetime
    model_config = ConfigDict(from_attributes=True)


class ConsultaCreateRequest(BaseModel):
    id_cita: int = Field(..., gt=0)
    motivo_consulta: str = Field(..., min_length=5)
    sintomas: str = Field(..., min_length=5)
    examen_fisico: Optional[str] = None
    signos_vitales: Optional[SignosVitalesSchema] = None
    observaciones: Optional[str] = None
    evolucion: str = Field(..., min_length=10)
    plan_medico: str = Field(..., min_length=5)
    datos_especialidad: Optional[Dict[str, Any]] = Field(default_factory=dict)
    diagnosticos: List[DiagnosticoCreateSchema] = Field(..., min_length=1)


class ConsultaResponseSchema(BaseModel):
    id_consulta: int
    id_clinica: int
    id_historia: int
    id_cita: int
    id_medico: int
    motivo_consulta: str
    sintomas: str
    examen_fisico: Optional[str]
    observaciones: Optional[str]
    evolucion: str
    plan_medico: str
    signos_vitales: Optional[Dict[str, Any]]
    datos_especialidad: Optional[Dict[str, Any]]
    fecha_consulta: datetime
    diagnosticos: List[DiagnosticoResponseSchema]
    model_config = ConfigDict(from_attributes=True)


class HistoriaClinicaBaseResponse(BaseModel):
    id_historia: int
    id_clinica: int
    id_paciente: int
    numero_historia: str
    antecedentes_personales: Optional[str]
    antecedentes_familiares: Optional[str]
    alergias: Optional[str]
    habitos: Optional[str]
    observaciones: Optional[str]
    fecha_creacion: datetime
    fecha_actualizacion: datetime
    model_config = ConfigDict(from_attributes=True)


class HistoriaClinicaCompletaResponse(HistoriaClinicaBaseResponse):
    consultas: List[ConsultaResponseSchema] = []
