"""Contratos Pydantic v2 del dominio backup (ver contracts/backup.md)."""

import re
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

DIAS_VALIDOS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
_HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class BackupFile(BaseModel):
    nombre: str
    tamanio: int
    fecha: str
    # Origen: "manual" (generada por un ADMIN, con auditoría CREAR) o
    # "automatica" (job programado user=None, sin auditoría manual).
    origen: str = "manual"


class BackupListResponse(BaseModel):
    data: List[BackupFile]


class BackupConfigOut(BaseModel):
    hora: str
    dias_semana: List[str]
    activo: bool
    retencion_dias: int
    ultima_ejecucion: Optional[str] = None
    ultimo_estado: Optional[str] = None


class BackupConfigUpdate(BaseModel):
    hora: str = Field(examples=["02:00"])
    dias_semana: List[str] = Field(examples=[["lun", "mar", "mie", "jue", "vie"]])
    activo: bool = True
    retencion_dias: int = Field(default=7, ge=1, le=365)

    @field_validator("hora")
    @classmethod
    def _hora_valida(cls, v: str) -> str:
        if not _HORA_RE.match(v):
            raise ValueError("hora debe tener formato HH:MM de 24h (ej. 02:00)")
        return v

    @field_validator("dias_semana")
    @classmethod
    def _dias_validos(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("dias_semana no puede estar vacío")
        mal = [d for d in v if d not in DIAS_VALIDOS]
        if mal:
            raise ValueError(f"días inválidos: {mal}. Use {DIAS_VALIDOS}")
        return v


class RestoreResponse(BaseModel):
    mensaje: str


class BackupEstado(BaseModel):
    ultima_ejecucion: Optional[str] = None
    ultimo_estado: Optional[str] = None


__all__ = [
    "BackupFile",
    "BackupListResponse",
    "BackupConfigOut",
    "BackupConfigUpdate",
    "RestoreResponse",
]
