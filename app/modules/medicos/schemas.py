from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Especialidades
# ---------------------------------------------------------------------------

class EspecialidadBase(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=100, examples=["Cardiología"])
    descripcion: Optional[str] = Field(None, max_length=1000, examples=["Diagnóstico y tratamiento de enfermedades del corazón"])


class EspecialidadCreate(EspecialidadBase):
    pass


class EspecialidadUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=3, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=1000)
    estado: Optional[str] = Field(None, pattern="^(activo|inactivo)$")


class EspecialidadResponse(BaseModel):
    id_especialidad: int
    nombre: str
    descripcion: Optional[str] = None
    estado: str

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Médicos
# ---------------------------------------------------------------------------

class MedicoCreate(BaseModel):
    id_usuario: int = Field(..., gt=0, examples=[1])
    matricula_profesional: str = Field(..., min_length=4, max_length=30, examples=["MAT-00001"])
    descripcion_profesional: Optional[str] = Field(None, max_length=2000, examples=["Médico cirujano con 10 años de experiencia"])
    experiencia: Optional[str] = Field(None, max_length=2000, examples=["Hospital Universitario, 2015-2020"])
    foto_perfil: Optional[str] = Field(None, max_length=500)
    especialidades: Optional[List[int]] = Field(None, examples=[[1, 2]])


class MedicoUpdate(BaseModel):
    matricula_profesional: Optional[str] = Field(None, min_length=4, max_length=30)
    descripcion_profesional: Optional[str] = Field(None, max_length=2000)
    experiencia: Optional[str] = Field(None, max_length=2000)
    foto_perfil: Optional[str] = Field(None, max_length=500)


class EstadoUpdate(BaseModel):
    nuevo_estado: str = Field(..., pattern="^(activo|inactivo)$", examples=["inactivo"])


class AsignacionEspecialidad(BaseModel):
    id_especialidad: int = Field(..., gt=0, examples=[1])
    es_principal: bool = False


class UsuarioInfo(BaseModel):
    id_usuario: int
    nombres: str
    apellidos: str
    correo: str
    telefono: Optional[str] = None
    foto_perfil: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EspecialidadMedico(BaseModel):
    id_especialidad: int
    nombre: str
    es_principal: bool

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def extraer_nombre(cls, data):
        # MedicoEspecialidad no tiene 'nombre' directo: viene por la relación 'especialidad'
        if hasattr(data, "especialidad") and getattr(data, "especialidad", None) is not None:
            if not isinstance(data, dict):
                return {
                    "id_especialidad": data.id_especialidad,
                    "nombre": data.especialidad.nombre,
                    "es_principal": data.es_principal,
                }
        return data


class MedicoResponse(BaseModel):
    id_medico: int
    id_usuario: int
    matricula_profesional: str
    descripcion_profesional: Optional[str] = None
    experiencia: Optional[str] = None
    foto_perfil: Optional[str] = None
    estado: str
    fecha_registro: datetime
    usuario: Optional[UsuarioInfo] = None
    especialidades: List[EspecialidadMedico] = []

    model_config = ConfigDict(from_attributes=True)


class MedicoListResponse(BaseModel):
    total: int
    items: List[MedicoResponse]
