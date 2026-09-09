from sqlalchemy import Column, BigInteger, Integer, String, Text, Boolean, Date, Time, Numeric, DateTime, ForeignKey, func, UniqueConstraint
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


class ServicioMedico(Base):
    __tablename__ = "servicios_medicos"

    id_servicio = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text)
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    duracion_minutos = Column(Integer, nullable=False)
    costo = Column(Numeric(10, 2), nullable=False)
    estado = Column(String(20), nullable=False)


class HorarioMedico(Base):
    __tablename__ = "horarios_medicos"
    __table_args__ = (UniqueConstraint("id_medico", "id_servicio", "dia_semana"),)

    id_horario = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id_medico = Column(BigInteger, ForeignKey("medicos.id_medico"), nullable=False)
    id_servicio = Column(BigInteger, ForeignKey("servicios_medicos.id_servicio"), nullable=False)
    dia_semana = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False, default="activo")
    medico = relationship("Medico")
    servicio = relationship("ServicioMedico")


class BloqueoAgenda(Base):
    __tablename__ = "bloqueos_agenda"

    # La exclusión GiST pertenece a la BD existente; no se simula en SQLite.
    id_bloqueo = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id_medico = Column(BigInteger, ForeignKey("medicos.id_medico"), nullable=False)
    id_servicio = Column(BigInteger, ForeignKey("servicios_medicos.id_servicio"), nullable=False)
    fecha = Column(Date, nullable=False)
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    motivo = Column(Text, nullable=False)
    estado = Column(String(20), nullable=False, default="PENDIENTE")
    medico = relationship("Medico")
    servicio = relationship("ServicioMedico")
