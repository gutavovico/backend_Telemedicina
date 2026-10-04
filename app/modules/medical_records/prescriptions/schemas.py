"""Esquemas Pydantic v2 CU16. Fuente: specs/openspec/contracts/prescriptions.md §3."""
from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class EstadoReceta(str, Enum):
    EMITIDA = "EMITIDA"
    ANULADA = "ANULADA"


class ViaAdministracion(str, Enum):
    ORAL = "ORAL"
    SUBLINGUAL = "SUBLINGUAL"
    INTRAMUSCULAR = "INTRAMUSCULAR"
    INTRAVENOSA = "INTRAVENOSA"
    TOPICA = "TOPICA"
    OFTALMICA = "OFTALMICA"
    INHALATORIA = "INHALATORIA"
    RECTAL = "RECTAL"
    OTRA = "OTRA"


# --------------------------------------------------------------------------- #
# Medicamentos
# --------------------------------------------------------------------------- #

class MedicamentoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    principio_activo: Optional[str] = Field(default=None, max_length=200)
    concentracion: Optional[str] = Field(default=None, max_length=100)
    forma_farmaceutica: Optional[str] = Field(default=None, max_length=100)
    descripcion: Optional[str] = None

    @field_validator("nombre", "principio_activo", "concentracion", "forma_farmaceutica", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value


class MedicamentoResponse(BaseModel):
    id_medicamento: int
    nombre: str
    principio_activo: Optional[str] = None
    concentracion: Optional[str] = None
    forma_farmaceutica: Optional[str] = None
    descripcion: Optional[str] = None
    estado: str

    model_config = {"from_attributes": True}


class MedicamentoListResponse(BaseModel):
    items: List[MedicamentoResponse]
    total: int


# --------------------------------------------------------------------------- #
# Recetas
# --------------------------------------------------------------------------- #

class RecetaDetalleCreate(BaseModel):
    id_medicamento: Optional[int] = None
    nombre_medicamento_manual: Optional[str] = Field(default=None, max_length=200)
    dosis: str = Field(min_length=1, max_length=100)
    frecuencia: str = Field(min_length=1, max_length=100)
    duracion: str = Field(min_length=1, max_length=100)
    via_administracion: ViaAdministracion
    cantidad: int = Field(gt=0)
    indicaciones: Optional[str] = None

    @model_validator(mode="after")
    def _xor_medicamento(self):
        tiene_catalogo = self.id_medicamento is not None
        manual = (self.nombre_medicamento_manual or "").strip()
        if tiene_catalogo and manual:
            raise ValueError("Use id_medicamento o nombre_medicamento_manual, no ambos")
        if not tiene_catalogo and not manual:
            raise ValueError("Debe indicar id_medicamento o nombre_medicamento_manual")
        if manual:
            self.nombre_medicamento_manual = manual
        return self


class RecetaCreateRequest(BaseModel):
    id_consulta: int
    id_paciente: int
    fecha_vencimiento: date
    indicaciones_generales: Optional[str] = None
    detalles: List[RecetaDetalleCreate] = Field(min_length=1)


class RecetaAnulacionRequest(BaseModel):
    motivo_anulacion: str = Field(min_length=15, max_length=500)
    observaciones_anulacion: Optional[str] = None
    id_receta_sustituta: Optional[int] = None


class RecetaDetalleResponse(BaseModel):
    id_receta_detalle: int
    id_medicamento: Optional[int] = None
    nombre_medicamento_manual: Optional[str] = None
    medicamento_nombre: str
    principio_activo: Optional[str] = None
    concentracion: Optional[str] = None
    forma_farmaceutica: Optional[str] = None
    dosis: str
    frecuencia: str
    duracion: str
    via_administracion: str
    cantidad: int
    indicaciones: Optional[str] = None
    posicion: int

    model_config = {"from_attributes": True}


class MedicoResumen(BaseModel):
    id_medico: int
    nombre_completo: str
    matricula_profesional: str
    especialidad: Optional[str] = None


class PacienteResumen(BaseModel):
    id_paciente: int
    nombre_completo: str


class RecetaResponse(BaseModel):
    id_receta: int
    id_clinica: int
    id_consulta: int
    id_paciente: int
    id_medico: int
    id_documento: Optional[int] = None
    id_receta_sustituta: Optional[int] = None
    folio: str
    pdf_url: str
    indicaciones_generales: Optional[str] = None
    algoritmo_firma: str
    key_id: str
    version_payload: int
    hash_pdf: str
    fecha_emision: str
    fecha_vencimiento: str
    esta_vencida: bool
    estado: str
    motivo_anulacion: Optional[str] = None
    observaciones_anulacion: Optional[str] = None
    fecha_anulacion: Optional[str] = None
    medico: MedicoResumen
    paciente: PacienteResumen
    detalles: List[RecetaDetalleResponse] = []


class RecetaListResponse(BaseModel):
    items: List[RecetaResponse]
    total: int


# --------------------------------------------------------------------------- #
# Validación pública
# --------------------------------------------------------------------------- #

class MedicoValidacionPublica(BaseModel):
    nombre: str
    matricula: str
    especialidad: Optional[str] = None


class PacienteValidacionPublica(BaseModel):
    nombre: str
    documento_identidad: str


class MedicamentoValidacionPublica(BaseModel):
    medicamento: str
    posologia: str
    cantidad: int
    indicaciones: Optional[str] = None


class RecetaValidacionPublicaResponse(BaseModel):
    valida: bool
    estado: str
    folio: Optional[str] = None
    fecha_emision: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    esta_vencida: Optional[bool] = None
    institucion: Optional[str] = None
    medico_emisor: Optional[MedicoValidacionPublica] = None
    paciente: Optional[PacienteValidacionPublica] = None
    medicamentos_prescritos: Optional[List[MedicamentoValidacionPublica]] = None
