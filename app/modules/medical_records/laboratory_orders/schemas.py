from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


CATALOGO_CATEGORIAS = ("HEMATOLOGIA", "BIOQUIMICA", "MICROBIOLOGIA", "INMUNOLOGIA", "OTROS")
ESTADOS_ORDEN = ("BORRADOR", "FIRMADA", "ANULADA")


class ExamenOrdenRequest(BaseModel):
    """Examen dentro de una orden de laboratorio."""

    codigo: str = Field(..., min_length=1, max_length=50, examples=["HEMOGRAMA"])
    indicaciones: Optional[str] = Field(None, max_length=500, examples=["En ayunas 12 horas"])

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, v: str) -> str:
        return v.strip().upper()


class ExamenLaboratorioResponse(BaseModel):
    """Respuesta de catálogo de exámenes."""

    id_examen: int
    id_clinica: int
    codigo: str
    nombre: str
    categoria: str
    precio_referencia: Optional[int] = None
    activo: str
    requiere_ayuno: int
    tiempo_entrega_horas: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExamenLaboratorioCreateRequest(BaseModel):
    """Payload para crear examen en catálogo (admin)."""

    codigo: str = Field(..., min_length=1, max_length=50, examples=["HEMOGRAMA"])
    nombre: str = Field(..., min_length=2, max_length=200, examples=["Hemograma Completo"])
    categoria: str = Field(..., examples=["HEMATOLOGIA"])
    precio_referencia: Optional[int] = Field(None, ge=0, examples=[15000])
    activo: str = Field(default="SI", examples=["SI"])
    requiere_ayuno: int = Field(default=0, ge=0, le=1, examples=[1])
    tiempo_entrega_horas: int = Field(default=24, ge=1, examples=[4])

    @field_validator("categoria")
    @classmethod
    def validar_categoria(cls, v: str) -> str:
        norm = v.strip().upper()
        if norm not in CATALOGO_CATEGORIAS:
            raise ValueError(f"Categoría inválida. Debe ser una de: {', '.join(CATALOGO_CATEGORIAS)}")
        return norm

    @field_validator("activo")
    @classmethod
    def validar_activo(cls, v: str) -> str:
        norm = v.strip().upper()
        if norm not in ("SI", "NO"):
            raise ValueError("activo debe ser 'SI' o 'NO'")
        return norm


class OrdenLaboratorioCreateRequest(BaseModel):
    """Payload para crear orden de laboratorio en borrador (CU10)."""

    id_paciente: int = Field(..., examples=[25])
    id_cita: Optional[int] = Field(None, examples=[100])
    examenes: List[ExamenOrdenRequest] = Field(..., min_length=1)

    @field_validator("examenes")
    @classmethod
    def validar_examenes_no_vacio(cls, v: List[ExamenOrdenRequest]) -> List[ExamenOrdenRequest]:
        if not v:
            raise ValueError("Debe incluir al menos un examen")
        return v


class OrdenLaboratorioFirmarRequest(BaseModel):
    """Payload para firmar orden (vacío, la firma se deriva del contenido)."""

    pass


class ExamenOrdenResponse(BaseModel):
    """Examen con nombre resuelto para respuesta."""

    codigo: str
    nombre: str
    indicaciones: Optional[str] = None


class OrdenLaboratorioResponse(BaseModel):
    """Respuesta completa de una orden de laboratorio."""

    id_orden: int
    id_clinica: int
    id_paciente: int
    id_cita: Optional[int] = None
    id_medico: int
    examenes: List[ExamenOrdenResponse]
    firma_digital: Optional[str] = None
    fecha_orden: date
    estado: str
    archivo_url: Optional[str] = None
    hash_archivo: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    paciente_nombre: Optional[str] = None
    medico_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OrdenLaboratorioListResponse(BaseModel):
    """Resumen para listados paginados."""

    id_orden: int
    id_clinica: int
    id_paciente: int
    paciente_nombre: Optional[str] = None
    examenes_codigos: List[str]
    estado: str
    fecha_orden: date
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrdenLaboratorioPaginationResponse(BaseModel):
    items: List[OrdenLaboratorioListResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class OrdenLaboratorioDownloadResponse(BaseModel):
    id_orden: int
    url_firmada: str
    expira_en: int
    nombre_archivo: str
    content_type: str