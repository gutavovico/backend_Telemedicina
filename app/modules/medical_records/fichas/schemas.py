from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SignosVitalesSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    presion_arterial: Optional[str] = None
    frecuencia_cardiaca: Optional[int] = None
    frecuencia_respiratoria: Optional[int] = None
    temperatura: Optional[float] = None
    saturacion_oxigeno: Optional[int] = None
    peso_kg: Optional[float] = None
    talla_cm: Optional[float] = None
    imc: Optional[float] = None


class FichaCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id_paciente: int = Field(..., alias="paciente_id")
    id_medico: int = Field(..., alias="medico_id")
    id_servicio: Optional[int] = Field(None, alias="servicio_id")
    id_especialidad: Optional[int] = Field(None, alias="especialidad_id")
    id_cita: Optional[int] = Field(None, alias="cita_id")

    fecha_atencion: date
    hora_inicio: str = Field(..., min_length=4, max_length=10)
    hora_fin: str = Field(..., min_length=4, max_length=10)

    motivo_consulta: str = Field(..., min_length=3)
    signos_vitales: Optional[Dict[str, Any]] = Field(default_factory=dict)
    secciones_dinamicas: Optional[Dict[str, Any]] = Field(default_factory=dict)


class FichaClinicaUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    signos_vitales: Optional[Dict[str, Any]] = None
    secciones_dinamicas: Optional[Dict[str, Any]] = None
    codigo_cie10: Optional[str] = None
    diagnostico_descripcion: Optional[str] = None
    id_diagnostico: Optional[int] = None
    notas_evolucion: Optional[str] = None
    estado: Optional[str] = None


class FichaCancelRequest(BaseModel):
    motivo_cancelacion: str = Field(..., min_length=3)


class FichaResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id_ficha: str
    id_clinica: int
    tenant_id: Optional[int] = None
    correlativo: str

    id_paciente: int
    paciente_id: Optional[int] = None
    paciente_nombre: Optional[str] = None
    paciente_ci: Optional[str] = None

    id_medico: int
    medico_id: Optional[int] = None
    medico_nombre: Optional[str] = None

    id_servicio: Optional[int] = None
    servicio_id: Optional[int] = None
    servicio_nombre: Optional[str] = None

    id_especialidad: Optional[int] = None
    especialidad_id: Optional[int] = None
    especialidad_nombre: Optional[str] = None

    id_cita: Optional[int] = None
    cita_id: Optional[int] = None

    fecha_emision: datetime
    fecha_atencion: date
    hora_inicio: str
    hora_fin: str

    motivo_consulta: str
    signos_vitales: Optional[Dict[str, Any]] = None
    secciones_dinamicas: Optional[Dict[str, Any]] = None

    codigo_cie10: Optional[str] = None
    diagnostico_descripcion: Optional[str] = None
    id_diagnostico: Optional[int] = None
    notas_evolucion: Optional[str] = None

    estado: str
    motivo_cancelacion: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class FichaListResponse(BaseModel):
    total: int
    items: List[FichaResponse]
