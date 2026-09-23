from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class AuditLogEntry(BaseModel):
    """Esquema de un registro de bitácora de auditoría (CU21)."""
    model_config = ConfigDict(from_attributes=True)

    id_auditoria: int = Field(..., description="ID único del registro de auditoría")
    id_clinica: Optional[int] = Field(None, description="ID de la clínica")
    tenant_id: Optional[Union[str, int]] = Field(None, description="Identificador del inquilino/clínica")
    id_usuario: int = Field(..., description="ID del usuario que realizó la acción")
    nombre_usuario: Optional[str] = Field(None, description="Nombre completo del usuario")
    correo_usuario: Optional[str] = Field(None, description="Correo electrónico del usuario")
    tabla_afectada: Optional[str] = Field(None, description="Tabla de BD afectada")
    registro_id: Optional[int] = Field(None, description="ID del registro afectado")
    accion: str = Field(..., description="Tipo de operación (INSERT, UPDATE, DELETE, SELECT, LOGIN, etc.)")
    descripcion: Optional[str] = Field(None, description="Descripción textual del evento")
    datos_anteriores: Optional[Union[Dict[str, Any], list, str]] = Field(None, description="Estado anterior")
    datos_nuevos: Optional[Union[Dict[str, Any], list, str]] = Field(None, description="Estado nuevo")
    direccion_ip: Optional[str] = Field(None, description="Dirección IP del cliente")
    fecha_hora: datetime = Field(..., description="Fecha y hora del evento")


class AuditLogListResponse(BaseModel):
    """Respuesta paginada para la consulta de bitácora."""
    data: List[AuditLogEntry]
    total: int
    page: int
    page_size: int
    total_pages: int


class AuditLogCreate(BaseModel):
    """Esquema interno para el registro automático de eventos de auditoría."""
    id_clinica: Optional[int] = None
    id_usuario: int
    tabla_afectada: Optional[str] = None
    registro_id: Optional[int] = None
    accion: str
    descripcion: Optional[str] = None
    datos_anteriores: Optional[Union[Dict[str, Any], list, str]] = None
    datos_nuevos: Optional[Union[Dict[str, Any], list, str]] = None
    direccion_ip: Optional[str] = None
