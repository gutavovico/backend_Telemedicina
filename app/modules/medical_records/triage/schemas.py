from typing import List, Optional
from pydantic import BaseModel, Field

class TriageForm(BaseModel):
    motivo: str = Field(..., description="Motivo principal: fiebre alta, dolor agudo, etc.")
    intensidad_dolor: int = Field(..., ge=1, le=10, description="1 a 10")
    tiempo_evolucion: str = Field(..., description="<2 horas, hoy/pocas horas, 24-48 horas, ms de 3 das")
    signos_alarma: List[str] = Field(default_factory=list)
    consulta_directa: str = Field(..., max_length=500)

class TriageResponse(BaseModel):
    nivel: int
    color: str
    descripcion_nivel: str
    tiempo_atencion_max_min: int
    posibles_causas: List[str] = Field(default_factory=list)
    recomendaciones: List[str] = Field(default_factory=list)
    motivo_clasificacion: str
    aviso: str = "Orientación preliminar, no sustituye una evaluación médica."

class TriageRecordResponse(BaseModel):
    id: int
    id_paciente: Optional[int]
    resultado_json: dict
    estado: str
