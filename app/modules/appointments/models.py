from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class Especialidad(Base):
    __tablename__ = "especialidades"

    id_especialidad = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
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

    id_medico = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
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
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    id_paciente = Column(
        BigInteger,
        ForeignKey("pacientes.id_paciente", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_medico = Column(
        BigInteger,
        ForeignKey("medicos.id_medico", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_especialidad = Column(
        BigInteger,
        ForeignKey("especialidades.id_especialidad", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Campo reservado para CU05/CU25
    id_servicio = Column(BigInteger, nullable=True)

    fecha_cita = Column(Date, nullable=True, index=True)
    hora_inicio = Column(String(10), nullable=True)
    hora_fin = Column(String(10), nullable=True)

    fecha_hora_inicio = Column(DateTime(timezone=False), nullable=True)
    fecha_hora_fin = Column(DateTime(timezone=False), nullable=True)
    modalidad = Column(String(50), nullable=True)
    motivo = Column(Text, nullable=True)
    estado = Column(String(30), nullable=True, default="PENDIENTE", server_default="PENDIENTE", index=True)
    tipo_consulta = Column(String(20), nullable=True, default="TELEMEDICINA", server_default="TELEMEDICINA")
    notas = Column(Text, nullable=True)
    check_in = Column(DateTime(timezone=False), nullable=True)
    fecha_creacion = Column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    paciente = relationship("Paciente", backref="citas")
    medico = relationship("Medico", backref="citas")
    especialidad = relationship("Especialidad")
    consultas = relationship(
        "Consulta", back_populates="cita", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Cita(id={self.id_cita}, paciente={self.id_paciente}, "
            f"medico={self.id_medico}, fecha={self.fecha_cita}, hora={self.hora_inicio}, estado='{self.estado}')>"
        )


class ServicioMedico(Base):
    __tablename__ = "servicios_medicos"

    id_servicio = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    duracion_minutos = Column(Integer, nullable=False)
    costo = Column(Numeric(10, 2), nullable=False)
    estado = Column(String(20), nullable=False, default="activo")

    def __repr__(self) -> str:
        return f"<ServicioMedico(id={self.id_servicio}, nombre='{self.nombre}', estado='{self.estado}')>"


class HorarioMedico(Base):
    __tablename__ = "horarios_medicos"
    __table_args__ = (UniqueConstraint("id_medico", "id_servicio", "dia_semana", name="uq_horarios_medico_servicio_dia"),)

    id_horario = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id_medico = Column(BigInteger, ForeignKey("medicos.id_medico", ondelete="CASCADE"), nullable=False, index=True)
    id_servicio = Column(BigInteger, ForeignKey("servicios_medicos.id_servicio", ondelete="CASCADE"), nullable=False, index=True)
    dia_semana = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False, default="activo")

    medico = relationship("Medico", backref="horarios")
    servicio = relationship("ServicioMedico", backref="horarios")

    def __repr__(self) -> str:
        return f"<HorarioMedico(id={self.id_horario}, medico={self.id_medico}, dia={self.dia_semana}, estado='{self.estado}')>"


class BloqueoAgenda(Base):
    __tablename__ = "bloqueos_agenda"

    id_bloqueo = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id_medico = Column(BigInteger, ForeignKey("medicos.id_medico", ondelete="CASCADE"), nullable=False, index=True)
    id_servicio = Column(BigInteger, ForeignKey("servicios_medicos.id_servicio", ondelete="CASCADE"), nullable=False, index=True)
    fecha = Column(Date, nullable=False, index=True)
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    motivo = Column(Text, nullable=False)
    estado = Column(String(20), nullable=False, default="PENDIENTE")

    medico = relationship("Medico", backref="bloqueos")
    servicio = relationship("ServicioMedico", backref="bloqueos")

    def __repr__(self) -> str:
        return f"<BloqueoAgenda(id={self.id_bloqueo}, medico={self.id_medico}, fecha={self.fecha}, estado='{self.estado}')>"

