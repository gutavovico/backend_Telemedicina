from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CitaBase(BaseModel):
    id_paciente: int = Field(..., description="ID del paciente")
    id_medico: int = Field(..., description="ID del médico")
    id_especialidad: Optional[int] = Field(None, description="ID de la especialidad")
    fecha_cita: date = Field(..., description="Fecha de la consulta (YYYY-MM-DD)")
    hora_inicio: str = Field(..., description="Hora de inicio (ej: '09:30')")
    hora_fin: Optional[str] = Field(None, description="Hora de fin estimada (ej: '10:00')")
    motivo: Optional[str] = Field(None, description="Motivo de la consulta")
    estado: Optional[str] = Field("PENDIENTE", description="Estado: PENDIENTE, CONFIRMADA, COMPLETADA, CANCELADA")
    tipo_consulta: Optional[str] = Field("TELEMEDICINA", description="Tipo: PRESENCIAL o TELEMEDICINA")
    notas: Optional[str] = Field(None, description="Notas adicionales")


class CitaCreate(CitaBase):
    pass


class CitaUpdate(BaseModel):
    id_paciente: Optional[int] = None
    id_medico: Optional[int] = None
    id_especialidad: Optional[int] = None
    fecha_cita: Optional[date] = None
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    motivo: Optional[str] = None
    estado: Optional[str] = None
    tipo_consulta: Optional[str] = None
    notas: Optional[str] = None


class CitaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_cita: int
    id_paciente: int
    id_medico: int
    id_especialidad: Optional[int] = None
    fecha_cita: date
    hora_inicio: str
    hora_fin: Optional[str] = None
    motivo: Optional[str] = None
    estado: str
    tipo_consulta: str
    notas: Optional[str] = None
    
    # Datos aplanados para respuestas enriquecidas
    paciente_nombre: str = ""
    paciente_ci: str = ""
    paciente_iniciales: str = ""
    medico_nombre: str = ""
    especialidad_nombre: Optional[str] = ""
    
    created_at: datetime
    updated_at: datetime


class CitaListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[CitaResponse]


class HorarioSlot(BaseModel):
    hora: str
    disponible: bool

