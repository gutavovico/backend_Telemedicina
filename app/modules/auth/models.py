from sqlalchemy import Column, BigInteger, String, func, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
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
    estado = Column(String(20), nullable=False, default="ACTIVO")

    rol_permisos = relationship("RolPermiso", back_populates="permiso", cascade="all, delete-orphan")
    roles = relationship("Rol", secondary="rol_permisos", back_populates="permisos", viewonly=True)

    def __repr__(self) -> str:
        return f"<Permiso(id={self.id_permiso}, nombre='{self.nombre}', estado='{self.estado}')>"


class Rol(Base):
    __tablename__ = "roles"
    id_rol = Column(BigInteger, primary_key=True, autoincrement=True)
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
    # Version del token: se incrementa para invalidar JWTs emitidos (logout global,
    # restablecimiento de contrasena en CU23). Existe en el esquema desplegado con
    # default 0 y NOT NULL; sin mapearla, cualquier alta fallaria.
    token_version = Column(BigInteger, nullable=False, server_default="0", default=0)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_actualizacion = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    rol_rel = relationship("Rol", foreign_keys=[id_rol], lazy="joined")

    @property
    def rol(self):
        """Nombre del rol (ADMIN, MEDICO, RECEPCION, PACIENTE).

        Lo consumen los guards por rol del frontend Angular y Flutter, que de otro
        modo recibirian `rol` siempre nulo y negarian el acceso.
        """
        return self.rol_rel.nombre if self.rol_rel else None

    @property
    def tenant_id(self):
        return self.id_clinica

    def __repr__(self) -> str:
        return f"<Usuario(id={self.id_usuario}, correo='{self.correo}', estado='{self.estado}')>"


class SesionActiva(Base):
    """Sesion autenticada individual, para medir inactividad por sesion (CU23).

    Existe una fila por par de tokens emitido en un login. `jti` es el claim que
    viaja dentro del JWT y coincide con la clave de revocacion. Sin esta tabla
    solo se podria medir la inactividad por usuario, lo que cerraria tambien los
    demas dispositivos que el usuario aun no ha cerrado (decision D1 del change).

    `ultima_actividad` se refresca en cada peticion autenticada dentro de la
    ventana configurada; `revocada_en` queda NULL mientras la sesion es valida.
    """

    __tablename__ = "sesiones_activas"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    id_usuario = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    id_clinica = Column(BigInteger, nullable=True)
    creada_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ultima_actividad = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revocada_en = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<SesionActiva(jti='{self.jti}', id_usuario={self.id_usuario})>"


class TokenBlacklist(Base):
    """Revocacion de una sesion concreta por `jti` (CU23).

    Tabla preexistente en el esquema desplegado de Neon, sin revision propia en
    el repositorio, y hasta ahora sin usar por ningun modulo. Se reutiliza tal
    cual (decision D2): la columna `token` almacena el `jti`, que es un UUID
    hexadecimal y encaja en el VARCHAR existente.

    El atributo Python se llama `revocada_en` para no filtrar el ingles al resto
    del dominio, pero se mapea a la columna REAL `revoked_at` que ya existe en
    Neon. Sin este mapeo explicito, SQLAlchemy buscaria una columna
    `revocada_en` inexistente y toda revocacion fallaria en live.
    """

    __tablename__ = "token_blacklist"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
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

    id_auditoria = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=False)
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
