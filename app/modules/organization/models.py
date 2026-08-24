from sqlalchemy import Column, BigInteger, String, func, DateTime
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