from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


TIPOS_DOCUMENTO = ("RECETA", "ORDEN_LAB", "RESULTADO_LAB", "CERTIFICADO", "INDICACION")


class DocumentoClinicoCreateRequest(BaseModel):
    """Payload para registrar/indexar un documento clínico en el tenant."""

    id_paciente: int = Field(..., examples=[10])
    id_cita: Optional[int] = Field(None, examples=[25])
    tipo_documento: str = Field(..., examples=["RECETA"])
    titulo: str = Field(..., min_length=3, max_length=200, examples=["Receta - Carlos Alberto Mamani"])
    descripcion: Optional[str] = Field(None)
    archivo_url: str = Field(..., min_length=1, max_length=500, examples=["documentos/1/2026/receta-001.pdf"])
    hash_archivo: str = Field(..., min_length=64, max_length=64, examples=["a" * 64])
    firmado_por: Optional[int] = Field(None, examples=[3])
    fecha_documento: date = Field(..., examples=["2026-09-01"])
    metadatos: Optional[Dict[str, Any]] = Field(None)

    @field_validator("tipo_documento")
    @classmethod
    def validar_tipo(cls, v: str) -> str:
        norm = v.strip().upper()
        if norm not in TIPOS_DOCUMENTO:
            raise ValueError(f"Tipo de documento inválido. Debe ser uno de: {', '.join(TIPOS_DOCUMENTO)}.")
        return norm

    @field_validator("hash_archivo")
    @classmethod
    def validar_hash(cls, v: str) -> str:
        h = v.strip().lower()
        if len(h) != 64 or not all(c in "0123456789abcdef" for c in h):
            raise ValueError("hash_archivo debe ser un SHA-256 hexadecimal de 64 caracteres.")
        return h

    @field_validator("fecha_documento")
    @classmethod
    def validar_fecha(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("La fecha del documento no puede ser posterior a la fecha actual.")
        return v


class DocumentoClinicoUpdateRequest(BaseModel):
    """Payload para actualizar metadata de un documento clínico (no el archivo)."""

    titulo: Optional[str] = Field(None, min_length=3, max_length=200)
    descripcion: Optional[str] = None
    metadatos: Optional[Dict[str, Any]] = None
    estado: Optional[str] = Field(None, examples=["ACTIVO"])

    @field_validator("estado")
    @classmethod
    def validar_estado(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        norm = v.strip().upper()
        if norm not in ("ACTIVO", "ANULADO"):
            raise ValueError("El estado debe ser 'ACTIVO' o 'ANULADO'.")
        return norm


class DocumentoClinicoResponse(BaseModel):
    """Respuesta completa de un documento clínico."""

    id_documento: int
    id_clinica: int
    tenant_id: Optional[int] = None
    id_paciente: Optional[int] = None
    id_cita: Optional[int] = None
    tipo_documento: str
    titulo: str
    descripcion: Optional[str] = None
    archivo_url: str
    hash_archivo: str
    firmado_por: Optional[int] = None
    fecha_documento: date
    metadatos: Optional[Dict[str, Any]] = None
    estado: str
    created_at: datetime
    updated_at: datetime
    paciente_nombre: Optional[str] = None
    firmante_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentoResumenResponse(BaseModel):
    """Resumen para listados paginados."""

    id_documento: int
    id_clinica: int
    id_paciente: Optional[int] = None
    tipo_documento: str
    titulo: str
    fecha_documento: date
    estado: str
    created_at: datetime
    paciente_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentoClinicoPaginationResponse(BaseModel):
    items: List[DocumentoResumenResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentoDownloadResponse(BaseModel):
    id_documento: int
    url_firmada: str
    expira_en: int
    nombre_archivo: str
    content_type: str