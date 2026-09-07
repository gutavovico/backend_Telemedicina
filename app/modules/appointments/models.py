from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Text,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    func,
    UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class Especialidad(Base):
    __tablename__ = "especialidades"

    id_especialidad = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    nombre = Column(String(100), nullable=False, unique=True)
    descripcion = Column(Text, nullable=True)
    estado = Column(String(20), nullable=False, default="activo")

    medicos = relationship(
        "MedicoEspecialidad",
        back_populates="especialidad",
        cascade="save-update, merge",
    )

    def __repr__(self) -> str:
        return f"<Especialidad(id={self.id_especialidad}, nombre='{self.nombre}', estado='{self.estado}')>"


class Medico(Base):
    __tablename__ = "medicos"

    id_medico = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    id_usuario = Column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    matricula_profesional = Column(String(30), nullable=False, unique=True, index=True)
    descripcion_profesional = Column(Text, nullable=True)
    experiencia = Column(Text, nullable=True)
    foto_perfil = Column(String(500), nullable=True)
    estado = Column(String(20), nullable=False, default="activo")
    fecha_registro = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    usuario = relationship("Usuario", backref="perfil_medico", uselist=False)
    especialidades = relationship(
        "MedicoEspecialidad",
        back_populates="medico",
        cascade="all, delete-orphan",
    )

    @property
    def tenant_id(self):
        return self.usuario.id_clinica if self.usuario else None

    def __repr__(self) -> str:
        return f"<Medico(id={self.id_medico}, id_usuario={self.id_usuario}, matricula='{self.matricula_profesional}', estado='{self.estado}')>"


class MedicoEspecialidad(Base):
    __tablename__ = "medico_especialidad"
    __table_args__ = (
        UniqueConstraint("id_medico", "id_especialidad", name="uq_medico_especialidad"),
    )

    id_medico = Column(
        BigInteger,
        ForeignKey("medicos.id_medico", ondelete="CASCADE"),
        primary_key=True,
    )
    id_especialidad = Column(
        BigInteger,
        ForeignKey("especialidades.id_especialidad", ondelete="CASCADE"),
        primary_key=True,
    )
    es_principal = Column(Boolean, nullable=False, default=False)

    medico = relationship("Medico", back_populates="especialidades")
    especialidad = relationship("Especialidad", back_populates="medicos")


class Cita(Base):
    __tablename__ = "citas"

    id_cita = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        index=True
    )
    id_paciente = Column(
        BigInteger,
        ForeignKey("pacientes.id_paciente", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    id_medico = Column(
        BigInteger,
        ForeignKey("medicos.id_medico", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    id_especialidad = Column(
        BigInteger,
        ForeignKey("especialidades.id_especialidad", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    fecha_cita = Column(Date, nullable=False, index=True)
    hora_inicio = Column(String(10), nullable=False)  # Formato "HH:MM", ej: "09:30"
    hora_fin = Column(String(10), nullable=True)     # Formato "HH:MM", ej: "10:00"
    motivo = Column(Text, nullable=True)
    estado = Column(String(20), nullable=False, default="PENDIENTE", index=True)  # PENDIENTE, CONFIRMADA, COMPLETADA, CANCELADA
    tipo_consulta = Column(String(20), nullable=False, default="TELEMEDICINA")   # PRESENCIAL, TELEMEDICINA
    notas = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    paciente = relationship("Paciente", backref="citas", lazy="joined")
    medico = relationship("Medico", backref="citas", lazy="joined")
    especialidad = relationship("Especialidad", lazy="joined")

    def __repr__(self) -> str:
        return f"<Cita(id={self.id_cita}, paciente={self.id_paciente}, medico={self.id_medico}, fecha={self.fecha_cita}, hora={self.hora_inicio}, estado='{self.estado}')>"
