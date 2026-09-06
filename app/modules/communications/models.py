from sqlalchemy import Column, BigInteger, Integer, String, func, DateTime, Text, ForeignKey
from app.core.database import Base


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
