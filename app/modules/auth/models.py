from sqlalchemy import Column, BigInteger, Integer, String, Text, func, DateTime, Boolean, ForeignKey, JSON, CheckConstraint, Numeric, UniqueConstraint

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.core.database import Base


class Clinica(Base):
    __tablename__ = "clinicas"
    id_clinica = Column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    tenant_id = Column(String(36), unique=True, nullable=True, index=True)
    nombre = Column(String(150), nullable=False)
    razon_social = Column(String(200), nullable=True)
    nit = Column(String(50), unique=True, nullable=True)
    telefono = Column(String(30), nullable=True)
    correo = Column(String(150), nullable=True)
    direccion = Column(String(250), nullable=True)
    logo = Column(String(500), nullable=True)
    estado = Column(String(20), nullable=False, default="ACTIVO")
    # Referencia canónica a la versión inmutable del catálogo CU34.
    # ``plan_id`` se conserva durante la transición para leer acuerdos legacy.
    id_version_plan = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        # La FK física se crea en la migración 020. Se omite en el modelo para
        # permitir fixtures SQLite que construyan solo un subconjunto de tablas.
        nullable=True,
        index=True,
    )
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

    def __eq__(self, other):
        if isinstance(other, str):
            return self.nombre == other
        return super().__eq__(other)

    def __hash__(self):
        return super().__hash__()

    def __str__(self) -> str:
        return self.nombre

    def __repr__(self) -> str:
        return f"<Rol(id={self.id_rol}, nombre='{self.nombre}', estado='{self.estado}')>"


class Usuario(Base):
    __tablename__ = "usuarios"
    id_usuario = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    # La migración 001 ya permite NULL; d2e3f4a5b6c7 incorpora el rol global.
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
    # La auditoría global puede ejecutarse sin id_clinica (CU30 y CU34).
    # La migración 020 elimina la restricción restrictiva de CU34.

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


_PLAN_ID = BigInteger().with_variant(Integer, "sqlite")


class Plan(Base):
    __tablename__ = "planes"
    id: Mapped[int] = mapped_column(_PLAN_ID, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version_actual: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    creado_en = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actualizado_en = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint("version_actual >= 1", name="ck_planes_version_positiva"),)


class VersionPlan(Base):
    __tablename__ = "versiones_plan"
    id: Mapped[int] = mapped_column(_PLAN_ID, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("planes.id", ondelete="RESTRICT"), nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(2000))
    precio_mensual = mapped_column(Numeric(14, 2), nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="BOB")
    ciclo: Mapped[str] = mapped_column(String(7), nullable=False, default="MENSUAL")
    servicios_incluidos = mapped_column(JSON, nullable=False)
    limite_medicos: Mapped[int | None] = mapped_column(Integer)
    limite_sedes: Mapped[int | None] = mapped_column(Integer)
    limite_consultas: Mapped[int | None] = mapped_column(Integer)
    tarifas_excedentes = mapped_column(JSON, nullable=False)
    demora_pago_dias: Mapped[int] = mapped_column(Integer, nullable=False)
    creado_por: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"), nullable=False)
    creado_en = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("plan_id", "numero", name="uq_versiones_plan_numero"),
        CheckConstraint("numero >= 1", name="ck_versiones_plan_numero"),
        CheckConstraint("precio_mensual >= 0 AND precio_mensual <= 999999999999.99", name="ck_versiones_plan_precio"),
        CheckConstraint("moneda = 'BOB' AND ciclo = 'MENSUAL'", name="ck_versiones_plan_moneda_ciclo"),
        CheckConstraint("limite_medicos IS NULL OR limite_medicos >= 0", name="ck_versiones_plan_medicos"),
        CheckConstraint("limite_sedes IS NULL OR limite_sedes >= 0", name="ck_versiones_plan_sedes"),
        CheckConstraint("limite_consultas IS NULL OR limite_consultas >= 0", name="ck_versiones_plan_consultas"),
        CheckConstraint("demora_pago_dias >= 0", name="ck_versiones_plan_demora"),
    )


__all__ = [
    "Clinica",
    "Rol",
    "RolPermiso",
    "Permiso",
    "Usuario",
    "SesionActiva",
    "TokenBlacklist",
    "Auditoria",
    "Plan",
    "VersionPlan",
]
