from sqlalchemy import (
    BigInteger,
    Column,
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


class HistoriaClinica(Base):
    __tablename__ = "historias_clinicas"

    id_historia = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    id_clinica = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("clinicas.id_clinica", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_paciente = Column(
        BigInteger,
        ForeignKey("pacientes.id_paciente", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    numero_historia = Column(String(100), nullable=False, index=True)
    antecedentes_personales = Column(Text, nullable=True)
    antecedentes_familiares = Column(Text, nullable=True)
    alergias = Column(Text, nullable=True)
    habitos = Column(Text, nullable=True)
    observaciones = Column(Text, nullable=True)
    fecha_creacion = Column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    fecha_actualizacion = Column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("id_clinica", "numero_historia", name="uq_hce_clinica_numero"),
        UniqueConstraint("id_clinica", "id_paciente", name="uq_hce_clinica_paciente"),
    )

    clinica = relationship("Clinica", backref="historias_clinicas")
    paciente = relationship("Paciente", backref="historia_clinica", uselist=False)
    consultas = relationship(
        "Consulta", back_populates="historia", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<HistoriaClinica(id={self.id_historia}, clinica={self.id_clinica}, "
            f"paciente={self.id_paciente}, numero='{self.numero_historia}')>"
        )


class Consulta(Base):
    __tablename__ = "consultas"

    id_consulta = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    id_clinica = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("clinicas.id_clinica", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_historia = Column(
        BigInteger,
        ForeignKey("historias_clinicas.id_historia", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_cita = Column(
        BigInteger,
        ForeignKey("citas.id_cita", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_medico = Column(
        BigInteger,
        ForeignKey("medicos.id_medico", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    motivo_consulta = Column(Text, nullable=False)
    sintomas = Column(Text, nullable=False)
    examen_fisico = Column(Text, nullable=True)
    signos_vitales = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    observaciones = Column(Text, nullable=True)
    evolucion = Column(Text, nullable=False)
    plan_medico = Column(Text, nullable=False)
    datos_especialidad = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    fecha_consulta = Column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    clinica = relationship("Clinica", backref="consultas")
    historia = relationship("HistoriaClinica", back_populates="consultas")
    cita = relationship("Cita", back_populates="consultas")
    medico = relationship("Medico", backref="consultas")
    diagnosticos = relationship(
        "Diagnostico", back_populates="consulta", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Consulta(id={self.id_consulta}, clinica={self.id_clinica}, "
            f"historia={self.id_historia}, cita={self.id_cita}, medico={self.id_medico})>"
        )


class Diagnostico(Base):
    __tablename__ = "diagnosticos"

    id_diagnostico = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    id_consulta = Column(
        BigInteger,
        ForeignKey("consultas.id_consulta", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    codigo_cie = Column(String(30), nullable=False, index=True)
    descripcion = Column(Text, nullable=False)
    tipo = Column(String(30), nullable=False)
    observaciones = Column(Text, nullable=True)
    fecha_registro = Column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    consulta = relationship("Consulta", back_populates="diagnosticos")

    def __repr__(self) -> str:
        return (
            f"<Diagnostico(id={self.id_diagnostico}, "
            f"cie='{self.codigo_cie}', tipo='{self.tipo}')>"
        )
