from sqlalchemy import Column, BigInteger, Integer, String, Text, func, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Clinica(Base):
    __tablename__ = "clinicas"
    id_clinica = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), unique=True, nullable=True, index=True)
    nombre = Column(String(150), nullable=False)
    razon_social = Column(String(200), nullable=True)
    nit = Column(String(50), unique=True, nullable=True)
    telefono = Column(String(30), nullable=True)
    correo = Column(String(150), nullable=True)
    direccion = Column(String(250), nullable=True)
    logo = Column(String(500), nullable=True)
    estado = Column(String(20), nullable=False, default="ACTIVO")
    plan_id = Column(String(36), nullable=True)
    commercial_notes = Column(Text, nullable=True)
    row_version = Column(Integer, nullable=False, default=1, server_default="1")
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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

    id_permiso = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String, nullable=True)
    modulo = Column(String(100), nullable=False)
    accion = Column(String(100), nullable=False)
    estado = Column(String(20), nullable=False, default="ACTIVO")

    rol_permisos = relationship("RolPermiso", back_populates="permiso", cascade="all, delete-orphan")
    roles = relationship("Rol", secondary="rol_permisos", back_populates="permisos", viewonly=True)

    def __repr__(self) -> str:
        return f"<Permiso(id={self.id_permiso}, nombre='{self.nombre}', estado='{self.estado}')>"


class Rol(Base):
    __tablename__ = "roles"
    id_rol = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String, nullable=True)
    estado = Column(String(20), nullable=False, default="ACTIVO")
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    rol_permisos = relationship("RolPermiso", back_populates="rol", cascade="all, delete-orphan")
    permisos = relationship("Permiso", secondary="rol_permisos", back_populates="roles", viewonly=True)

    def __repr__(self) -> str:
        return f"<Rol(id={self.id_rol}, nombre='{self.nombre}', estado='{self.estado}')>"


class Usuario(Base):
    __tablename__ = "usuarios"
    id_usuario = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=True)
    id_rol = Column(BigInteger, ForeignKey("roles.id_rol"), nullable=True)
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
    token_version = Column(BigInteger, nullable=False, server_default="0", default=0)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_actualizacion = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    rol_rel = relationship("Rol", foreign_keys=[id_rol], lazy="joined")

    @property
    def rol(self):
        return self.rol_rel.nombre if self.rol_rel else None

    @property
    def tenant_id(self):
        return self.id_clinica

    def __repr__(self) -> str:
        return f"<Usuario(id={self.id_usuario}, correo='{self.correo}', estado='{self.estado}')>"


class SesionActiva(Base):
    __tablename__ = "sesiones_activas"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    id_usuario = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    id_clinica = Column(BigInteger, nullable=True)
    creada_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ultima_actividad = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revocada_en = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<SesionActiva(jti='{self.jti}', id_usuario={self.id_usuario})>"


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    token = Column(String(500), nullable=False, index=True)
    revocada_en = Column(
        "revoked_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TokenBlacklist(token='{self.token}')>"


class Auditoria(Base):
    __tablename__ = "auditoria"

    id_auditoria = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=True)
    id_usuario = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    tabla_afectada = Column(String(150), nullable=True)
    registro_id = Column(BigInteger, nullable=True)
    accion = Column(String(50), nullable=False)
    descripcion = Column(String, nullable=True)
    datos_anteriores = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    datos_nuevos = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    direccion_ip = Column(String(45), nullable=True)
    fecha_hora = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<Auditoria(id={self.id_auditoria}, accion='{self.accion}', tabla='{self.tabla_afectada}')>"


__all__ = [
    "Clinica",
    "Rol",
    "RolPermiso",
    "Permiso",
    "Usuario",
    "SesionActiva",
    "TokenBlacklist",
    "Auditoria",
]
