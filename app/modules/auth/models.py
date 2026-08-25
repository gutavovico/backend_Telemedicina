from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Clinica(Base):
    __tablename__ = "clinicas"

    id_clinica = Column(BigInteger, primary_key=True, autoincrement=True, index=True)

    usuarios = relationship("Usuario", back_populates="clinica")
    roles = relationship("Rol", back_populates="clinica")

    def __repr__(self) -> str:
        return f"<Clinica(id={self.id_clinica})>"


class RolPermiso(Base):
    __tablename__ = "rol_permisos"

    id_rol = Column(BigInteger, ForeignKey("roles.id_rol"), primary_key=True)
    id_permiso = Column(BigInteger, ForeignKey("permisos.id_permiso"), primary_key=True)

    rol = relationship("Rol", back_populates="rol_permisos")
    permiso = relationship("Permiso", back_populates="rol_permisos")

    def __repr__(self) -> str:
        return f"<RolPermiso(id_rol={self.id_rol}, id_permiso={self.id_permiso})>"


class Permiso(Base):
    __tablename__ = "permisos"

    id_permiso = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String, nullable=True)
    modulo = Column(String(100), nullable=False)
    accion = Column(String(100), nullable=False)
    estado = Column(String(20), nullable=False)

    rol_permisos = relationship("RolPermiso", back_populates="permiso", cascade="all, delete-orphan")
    roles = relationship("Rol", secondary="rol_permisos", back_populates="permisos", viewonly=True)

    def __repr__(self) -> str:
        return f"<Permiso(id={self.id_permiso}, nombre='{self.nombre}', estado='{self.estado}')>"


class Rol(Base):
    __tablename__ = "roles"

    id_rol = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String, nullable=True)
    estado = Column(String(20), nullable=False)

    clinica = relationship("Clinica", back_populates="roles")
    usuarios = relationship("Usuario", back_populates="rol")
    rol_permisos = relationship("RolPermiso", back_populates="rol", cascade="all, delete-orphan")
    permisos = relationship("Permiso", secondary="rol_permisos", back_populates="roles", viewonly=True)

    def __repr__(self) -> str:
        return f"<Rol(id={self.id_rol}, nombre='{self.nombre}', estado='{self.estado}')>"


class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=True)
    id_rol = Column(BigInteger, ForeignKey("roles.id_rol"), nullable=True)
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

    clinica = relationship("Clinica", back_populates="usuarios")
    rol = relationship("Rol", back_populates="usuarios")

    def __repr__(self) -> str:
        return f"<Usuario(id={self.id_usuario}, correo='{self.correo}', estado='{self.estado}')>"
