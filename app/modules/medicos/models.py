from sqlalchemy import Column, BigInteger, String, Text, Boolean, DateTime, ForeignKey, func, UniqueConstraint
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
