from datetime import date, datetime
from typing import Optional
from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class DocumentoClinico(Base):
    """Documento clínico indexable (CU12 - Consultar Documentos Clínicos y Exámenes)."""

    __tablename__ = "documentos_clinicos"

    id_documento = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("clinicas.id_clinica"), nullable=False, index=True)
    id_paciente = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("pacientes.id_paciente"), nullable=True, index=True)
    id_cita = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True)
    tipo_documento = Column(String(30), nullable=False, index=True)  # RECETA, ORDEN_LAB, RESULTADO_LAB, CERTIFICADO, INDICACION
    titulo = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)
    archivo_url = Column(String(500), nullable=False)
    hash_archivo = Column(String(64), nullable=False)
    firmado_por = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("usuarios.id_usuario"), nullable=True)
    fecha_documento = Column(Date, nullable=False, index=True)
    metadatos = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    estado = Column(String(20), nullable=False, default="ACTIVO")  # ACTIVO, ANULADO
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    paciente = relationship("Paciente", backref="documentos_clinicos", lazy="joined")
    firmante = relationship("Usuario", foreign_keys=[firmado_por], lazy="joined")

    __table_args__ = (
        Index("idx_docs_clinica_paciente", "id_clinica", "id_paciente"),
        Index("idx_docs_clinica_tipo", "id_clinica", "tipo_documento"),
        Index("idx_docs_clinica_fecha", "id_clinica", "fecha_documento"),
    )

    @property
    def tenant_id(self):
        return str(self.id_clinica) if self.id_clinica is not None else None

    def __repr__(self) -> str:
        return f"<DocumentoClinico(id={self.id_documento}, tipo='{self.tipo_documento}', estado='{self.estado}')>"