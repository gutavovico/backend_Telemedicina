from sqlalchemy import Column, BigInteger, String, func, DateTime, Text, ForeignKey
from app.core.database import Base


class Notificacion(Base):
    __tablename__ = "notificaciones"
    id_notificacion = Column(BigInteger, primary_key=True, autoincrement=True)
    id_usuario = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    tipo = Column(String(50), nullable=True)
    canal = Column(String(30), nullable=True)
    titulo = Column(String(200), nullable=True)
    mensaje = Column(Text, nullable=True)
    fecha_programada = Column(DateTime(timezone=True), nullable=True)
    fecha_envio = Column(DateTime(timezone=True), nullable=True)
    fecha_lectura = Column(DateTime(timezone=True), nullable=True)
    estado = Column(String(30), nullable=False, default="PENDIENTE")


class Auditoria(Base):
    __tablename__ = "auditoria"
    id_auditoria = Column(BigInteger, primary_key=True, autoincrement=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_usuario = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    tabla_afectada = Column(String(150), nullable=True)
    registro_id = Column(BigInteger, nullable=True)
    accion = Column(String(50), nullable=False)
    descripcion = Column(Text, nullable=True)
    datos_anteriores = Column(Text, nullable=True)
    datos_nuevos = Column(Text, nullable=True)
    direccion_ip = Column(String(45), nullable=True)
    fecha_hora = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)