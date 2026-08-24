from sqlalchemy import Column, BigInteger, String, func, DateTime, Boolean, ForeignKey
from app.core.database import Base


class Clinica(Base):
    __tablename__ = "clinicas"
    id_clinica = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(150), nullable=False)
    razon_social = Column(String(200), nullable=True)
    nit = Column(String(50), unique=True, nullable=True)
    telefono = Column(String(30), nullable=True)
    correo = Column(String(150), nullable=True)
    direccion = Column(String(250), nullable=True)
    logo = Column(String(500), nullable=True)
    estado = Column(String(20), nullable=False, default="ACTIVO")
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Rol(Base):
    __tablename__ = "roles"
    id_rol = Column(BigInteger, primary_key=True, autoincrement=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String, nullable=True)
    estado = Column(String(20), nullable=False, default="ACTIVO")
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Usuario(Base):
    __tablename__ = "usuarios"
    id_usuario = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_rol = Column(BigInteger, ForeignKey("roles.id_rol"), nullable=False)
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    correo = Column(String(150), unique=True, nullable=False, index=True)
    telefono = Column(String(30), nullable=True)
    password_hash = Column(String(255), nullable=False)
    foto_perfil = Column(String(500), nullable=True)
    estado = Column(String(20), nullable=False, default="ACTIVO")
    notificaciones_push = Column(Boolean, default=True, nullable=False)
    notificaciones_email = Column(Boolean, default=True, nullable=False)
    notificaciones_sms = Column(Boolean, default=False, nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_actualizacion = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<Usuario(id={self.id_usuario}, correo='{self.correo}', estado='{self.estado}')>"