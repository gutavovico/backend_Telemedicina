from datetime import date, datetime
from typing import Optional
from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class ExamenLaboratorio(Base):
    """Catálogo de exámenes de laboratorio por clínica (CU10)."""

    __tablename__ = "examenes_laboratorio"

    id_examen = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=False, index=True)
    codigo = Column(String(50), nullable=False, index=True)
    nombre = Column(String(200), nullable=False)
    categoria = Column(String(50), nullable=False)  # HEMATOLOGIA, BIOQUIMICA, MICROBIOLOGIA, INMUNOLOGIA, OTROS
    precio_referencia = Column(BigInteger, nullable=True)  # En centavos para evitar float
    activo = Column(String(10), nullable=False, default="SI")  # SI, NO
    requiere_ayuno = Column(BigInteger, nullable=False, default=0)  # 0/1
    tiempo_entrega_horas = Column(BigInteger, nullable=False, default=24)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_examenes_clinica_codigo", "id_clinica", "codigo", unique=True),
        Index("idx_examenes_clinica_activo", "id_clinica", "activo"),
    )

    @property
    def tenant_id(self):
        return self.id_clinica

    def __repr__(self) -> str:
        return f"<ExamenLaboratorio(codigo='{self.codigo}', nombre='{self.nombre}', activo='{self.activo}')>"


class OrdenLaboratorio(Base):
    """Orden de exámenes de laboratorio firmada digitalmente (CU10).

    Se integra con HCE (CU12): al firmar, se genera PDF y se indexa en
    `documentos_clinicos` con `tipo_documento = 'ORDEN_LAB'`.
    """

    __tablename__ = "ordenes_laboratorio"

    id_orden = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=False, index=True)
    id_paciente = Column(BigInteger, nullable=False, index=True)  # Sin FK a pacientes (tabla legacy)
    id_cita = Column(BigInteger, nullable=True)
    id_medico = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False, index=True)
    examenes = Column(JSONB, nullable=False)  # [{"codigo", "nombre", "indicaciones"}]
    firma_digital = Column(String(64), nullable=True)  # HMAC-SHA256 hex
    fecha_orden = Column(Date, nullable=False, index=True)
    estado = Column(String(20), nullable=False, default="BORRADOR")  # BORRADOR, FIRMADA, ANULADA
    archivo_url = Column(String(500), nullable=True)  # Object key en storage
    hash_archivo = Column(String(64), nullable=True)  # SHA-256 del PDF
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    medico = relationship("Usuario", foreign_keys=[id_medico], lazy="joined")

    __table_args__ = (
        Index("idx_ordenes_clinica_paciente", "id_clinica", "id_paciente"),
        Index("idx_ordenes_clinica_medico", "id_clinica", "id_medico"),
        Index("idx_ordenes_clinica_estado", "id_clinica", "estado"),
        Index("idx_ordenes_clinica_fecha", "id_clinica", "fecha_orden"),
    )

    @property
    def tenant_id(self):
        return self.id_clinica

    def __repr__(self) -> str:
        return f"<OrdenLaboratorio(id={self.id_orden}, estado='{self.estado}', medico={self.id_medico})>"