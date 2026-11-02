"""Entidades del dominio backup (tabla global, sin tenant)."""

from datetime import datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class BackupConfig(Base):
    """Programación global de copias automáticas (una sola fila, id=1)."""

    __tablename__ = "backup_config"

    id = Column(Integer, primary_key=True, autoincrement=False, default=1)
    hora = Column(String(5), nullable=False, server_default="02:00")
    dias_semana = Column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default='["lun", "mar", "mie", "jue", "vie", "sab", "dom"]',
    )
    activo = Column(Boolean, nullable=False, server_default="true")
    retencion_dias = Column(Integer, nullable=False, server_default="7")
    updated_by = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<BackupConfig(hora='{self.hora}', activo={self.activo})>"


__all__ = ["BackupConfig"]
