from sqlalchemy import Column, BigInteger, Integer, String, Boolean, func, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.modules.auth.models import Usuario
from app.modules.appointments.models import Cita


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id_notificacion = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_usuario = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    tipo = Column(String(50), nullable=True)
    canal = Column(String(30), nullable=True)
    titulo = Column(String(200), nullable=True)
    mensaje = Column(Text, nullable=True)
    fecha_programada = Column(DateTime(timezone=True), nullable=True)
    fecha_envio = Column(DateTime(timezone=True), nullable=True)
    fecha_lectura = Column(DateTime(timezone=True), nullable=True)
    estado = Column(String(30), nullable=False, default="PENDIENTE")

    def __repr__(self) -> str:
        return f"<Notificacion(id={self.id_notificacion}, titulo='{self.titulo}', estado='{self.estado}')>"


class MensajeChatCita(Base):
    """Mensajes de chat interactivo entre paciente y médico vinculados a una cita médica (CU15)."""
    __tablename__ = "mensajes_chat_cita"

    id_mensaje = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True
    )
    id_clinica = Column(
        BigInteger,
        ForeignKey("clinicas.id_clinica", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    id_cita = Column(
        BigInteger,
        ForeignKey("citas.id_cita", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    id_remitente = Column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    rol_remitente = Column(String(20), nullable=False, default="PACIENTE")
    contenido = Column(Text, nullable=False)
    adjunto_nombre = Column(String(255), nullable=True)
    adjunto_tamano = Column(String(50), nullable=True)
    adjunto_url = Column(Text, nullable=True)
    leido = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    cita = relationship("Cita", backref="mensajes_chat")
    remitente = relationship("Usuario", foreign_keys=[id_remitente])

    def __repr__(self) -> str:
        return f"<MensajeChatCita(id={self.id_mensaje}, id_cita={self.id_cita}, remitente={self.id_remitente})>"


class SesionTeleconsulta(Base):
    """Sesión de teleconsulta y videoconsulta médica en tiempo real (CU14)."""
    __tablename__ = "sesiones_teleconsulta"

    id_teleconsulta = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica", ondelete="CASCADE"), nullable=False, index=True)
    id_cita = Column(BigInteger, ForeignKey("citas.id_cita", ondelete="CASCADE"), nullable=False, index=True)
    id_medico = Column(BigInteger, ForeignKey("medicos.id_medico", ondelete="CASCADE"), nullable=False, index=True)
    id_paciente = Column(BigInteger, ForeignKey("pacientes.id_paciente", ondelete="CASCADE"), nullable=False, index=True)
    codigo_ficha = Column(String(50), nullable=False, default="FICHA-CU14")
    estado = Column(String(30), nullable=False, default="EN_ESPERA")
    posicion_fila = Column(Integer, nullable=False, default=1)
    pacientes_antes = Column(Integer, nullable=False, default=0)
    tiempo_estimado_minutos = Column(Integer, nullable=False, default=10)
    duracion_segundos = Column(Integer, nullable=False, default=0)
    calidad_red = Column(String(30), nullable=False, default="HD 1080p")
    cifrado_activo = Column(Boolean, nullable=False, default=True)
    doctor_conectado = Column(Boolean, nullable=False, default=False)
    paciente_conectado = Column(Boolean, nullable=False, default=False)
    compartiendo_pantalla = Column(Boolean, nullable=False, default=False)
    camara_activa_paciente = Column(Boolean, nullable=False, default=True)
    microfono_activo_paciente = Column(Boolean, nullable=False, default=True)
    fecha_inicio = Column(DateTime(timezone=True), nullable=True)
    fecha_fin = Column(DateTime(timezone=True), nullable=True)
    motivo_evolucion = Column(Text, nullable=True)
    examen_fisico = Column(Text, nullable=True)
    diagnostico_cie10 = Column(String(255), nullable=True)
    plan_tratamiento = Column(Text, nullable=True)
    presion_arterial = Column(String(50), nullable=True)
    frecuencia_cardiaca = Column(String(50), nullable=True)
    peso_kg = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    cita = relationship("Cita", backref="sesion_teleconsulta")
    medico = relationship("Medico", foreign_keys=[id_medico])
    paciente = relationship("Paciente", foreign_keys=[id_paciente])

    def __repr__(self) -> str:
        return f"<SesionTeleconsulta(id={self.id_teleconsulta}, id_cita={self.id_cita}, estado='{self.estado}')>"


class VerificacionEquipoTeleconsulta(Base):
    """Verificación de periféricos previa a la entrada en videoconsulta (CU14)."""
    __tablename__ = "verificaciones_equipo_teleconsulta"

    id_verificacion = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_teleconsulta = Column(BigInteger, ForeignKey("sesiones_teleconsulta.id_teleconsulta", ondelete="CASCADE"), nullable=False, index=True)
    camara_verificada = Column(Boolean, nullable=False, default=True)
    microfono_verificado = Column(Boolean, nullable=False, default=True)
    conexion_calidad = Column(String(50), nullable=False, default="Buena")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sesion = relationship("SesionTeleconsulta", backref="verificaciones")

    def __repr__(self) -> str:
        return f"<VerificacionEquipoTeleconsulta(id={self.id_verificacion}, id_teleconsulta={self.id_teleconsulta})>"
