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
