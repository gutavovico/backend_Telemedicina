from sqlalchemy import Column, BigInteger, Integer, String, Boolean, DateTime, func
from app.core.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, nullable=True, index=True)
    id_rol = Column(BigInteger, nullable=True, index=True)
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    correo = Column(String(150), unique=True, nullable=False, index=True)
    telefono = Column(String(20), nullable=True)
    password_hash = Column(String(255), nullable=False)
    foto_perfil = Column(String(500), nullable=True)
    estado = Column(String(20), nullable=False, default="activo")
    notificaciones_push = Column(Boolean, default=True, nullable=False)
    notificaciones_email = Column(Boolean, default=True, nullable=False)
    notificaciones_sms = Column(Boolean, default=False, nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_actualizacion = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<Usuario(id={self.id_usuario}, correo='{self.correo}', estado='{self.estado}')>"
