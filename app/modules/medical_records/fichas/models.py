import uuid
from datetime import date, datetime
from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class FichaClinica(Base):
    __tablename__ = "fichas_clinicas"

    id_ficha = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    id_clinica = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("clinicas.id_clinica", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    correlativo = Column(String(50), nullable=False, index=True)
    id_paciente = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("pacientes.id_paciente", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_medico = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("medicos.id_medico", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_servicio = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("servicios_medicos.id_servicio", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    id_especialidad = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("especialidades.id_especialidad", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    id_cita = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("citas.id_cita", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    fecha_emision = Column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    fecha_atencion = Column(Date, nullable=False, index=True)
    hora_inicio = Column(String(10), nullable=False)
    hora_fin = Column(String(10), nullable=False)

    motivo_consulta = Column(Text, nullable=False)
    signos_vitales = Column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True, default=dict
    )
    secciones_dinamicas = Column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True, default=dict
    )

    codigo_cie10 = Column(String(30), nullable=True, index=True)
    diagnostico_descripcion = Column(Text, nullable=True)
    id_diagnostico = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("diagnosticos.id_diagnostico", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notas_evolucion = Column(Text, nullable=True)

    estado = Column(
        String(30), default="EMITIDA", nullable=False, index=True
    )  # EMITIDA, EN_ATENCION, FINALIZADA, CANCELADA
    motivo_cancelacion = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "id_clinica", "correlativo", name="uq_fichas_clinica_correlativo"
        ),
        UniqueConstraint(
            "id_clinica",
            "id_medico",
            "fecha_atencion",
            "hora_inicio",
            name="uq_fichas_medico_slot",
        ),
    )

    clinica = relationship("Clinica", backref="fichas_clinicas")
    paciente = relationship("Paciente", backref="fichas_clinicas")
    medico = relationship("Medico", backref="fichas_clinicas")
    servicio = relationship("ServicioMedico", backref="fichas_clinicas")
    especialidad = relationship("Especialidad", backref="fichas_clinicas")
    cita = relationship("Cita", backref="fichas_clinicas")
    diagnostico = relationship("Diagnostico", backref="fichas_clinicas")

    @property
    def tenant_id(self):
        return self.id_clinica

    def __repr__(self) -> str:
        return (
            f"<FichaClinica(id='{self.id_ficha}', correlativo='{self.correlativo}', "
            f"clinica={self.id_clinica}, paciente={self.id_paciente}, estado='{self.estado}')>"
        )
