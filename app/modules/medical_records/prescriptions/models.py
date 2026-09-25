"""Modelos CU16 - Recetas Médicas Digitales.

Ver specs/openspec/changes/cu16-recetas-digitales/design.md § Data Model.
Compatibles con PostgreSQL y SQLite (variantes Integer/JSON para tests).
"""
from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Medicamento(Base):
    """Catálogo global de medicamentos (sin id_clinica por diseño)."""

    __tablename__ = "medicamentos"

    id_medicamento = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    nombre = Column(String(200), nullable=False)
    principio_activo = Column(String(200), nullable=True)
    concentracion = Column(String(100), nullable=True)
    forma_farmaceutica = Column(String(100), nullable=True)
    descripcion = Column(Text, nullable=True)
    estado = Column(String(20), nullable=False, default="ACTIVO")  # ACTIVO | INACTIVO
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("estado IN ('ACTIVO', 'INACTIVO')", name="ck_medicamentos_estado"),
        Index("ix_medicamentos_nombre", "nombre"),
        Index("ix_medicamentos_estado", "estado"),
        # Unicidad funcional normalizada (nombre, concentracion, forma) en
        # minúsculas; evita duplicados que difieren solo en mayúsculas o
        # espacios. Equivale a uq_medicamentos_normalizado de la migración
        # CU16 (PostgreSQL). En SQLite se expresa con func.lower/coalesce.
        Index(
            "uq_medicamentos_normalizado",
            func.lower(nombre),
            func.coalesce(func.lower(concentracion), ""),
            func.coalesce(func.lower(forma_farmaceutica), ""),
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<Medicamento(id={self.id_medicamento}, nombre='{self.nombre}', estado='{self.estado}')>"


class Receta(Base):
    """Receta médica digital: documento clínico legal e inmutable."""

    __tablename__ = "recetas"

    id_receta = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id_clinica = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("clinicas.id_clinica"), nullable=False)
    id_consulta = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("consultas.id_consulta"), nullable=False)
    id_medico = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("medicos.id_medico"), nullable=False)
    id_paciente = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("pacientes.id_paciente"), nullable=False)
    id_documento = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("documentos_clinicos.id_documento"), nullable=True, unique=True)
    id_receta_sustituta = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("recetas.id_receta"), nullable=True)
    folio = Column(String(40), nullable=False)
    codigo_verificacion_hash = Column(CHAR(64), nullable=False, unique=True)
    indicaciones_generales = Column(Text, nullable=True)
    firma_digital = Column(Text, nullable=False)
    algoritmo_firma = Column(String(20), nullable=False, default="ED25519")
    key_id = Column(String(100), nullable=False)
    version_payload = Column(SmallInteger, nullable=False, default=1)
    hash_pdf = Column(CHAR(64), nullable=False)
    fecha_emision = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)
    estado = Column(String(20), nullable=False, default="EMITIDA")  # EMITIDA | ANULADA
    motivo_anulacion = Column(Text, nullable=True)
    observaciones_anulacion = Column(Text, nullable=True)
    fecha_anulacion = Column(DateTime(timezone=True), nullable=True)
    anulado_por = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("usuarios.id_usuario"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("id_clinica", "folio", name="uq_recetas_clinica_folio"),
        CheckConstraint("estado IN ('EMITIDA', 'ANULADA')", name="ck_recetas_estado"),
        CheckConstraint("algoritmo_firma = 'ED25519'", name="ck_recetas_algoritmo"),
        Index("ix_recetas_clinica_paciente", "id_clinica", "id_paciente"),
        Index("ix_recetas_clinica_medico", "id_clinica", "id_medico"),
        Index("ix_recetas_clinica_estado", "id_clinica", "estado"),
        Index("ix_recetas_clinica_emision", "id_clinica", "fecha_emision"),
        Index("ix_recetas_consulta", "id_consulta"),
    )

    detalles = relationship("RecetaDetalle", back_populates="receta", cascade="all, delete-orphan", order_by="RecetaDetalle.posicion")
    # Carga diferida: evita joinedloads que encadenen a Usuario.rol, cuyo esquema
    # físico difiere del ORM en PostgreSQL (divergencia pre-existente, ver CU12).
    documento = relationship("DocumentoClinico", foreign_keys=[id_documento], lazy="select")

    @property
    def tenant_id(self):
        return str(self.id_clinica) if self.id_clinica is not None else None

    def __repr__(self) -> str:
        return f"<Receta(id={self.id_receta}, folio='{self.folio}', estado='{self.estado}')>"


class RecetaDetalle(Base):
    """Detalle de receta con snapshot inmutable y selección XOR catálogo/manual."""

    __tablename__ = "receta_detalle"

    id_receta_detalle = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id_receta = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("recetas.id_receta", ondelete="CASCADE"), nullable=False)
    id_medicamento = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("medicamentos.id_medicamento", ondelete="RESTRICT"), nullable=True)
    nombre_medicamento_manual = Column(String(200), nullable=True)
    medicamento_nombre = Column(String(200), nullable=False)
    principio_activo = Column(String(200), nullable=True)
    concentracion = Column(String(100), nullable=True)
    forma_farmaceutica = Column(String(100), nullable=True)
    dosis = Column(String(100), nullable=False)
    frecuencia = Column(String(100), nullable=False)
    duracion = Column(String(100), nullable=False)
    via_administracion = Column(String(30), nullable=False)
    cantidad = Column(Integer, nullable=False)
    indicaciones = Column(Text, nullable=True)
    posicion = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "via_administracion IN ('ORAL', 'SUBLINGUAL', 'INTRAMUSCULAR', 'INTRAVENOSA', "
            "'TOPICA', 'OFTALMICA', 'INHALATORIA', 'RECTAL', 'OTRA')",
            name="ck_receta_detalle_via",
        ),
        CheckConstraint("cantidad > 0", name="ck_receta_detalle_cantidad"),
        CheckConstraint(
            "(id_medicamento IS NOT NULL AND nombre_medicamento_manual IS NULL) "
            "OR (id_medicamento IS NULL AND nombre_medicamento_manual IS NOT NULL "
            "AND nombre_medicamento_manual <> '')",
            name="ck_receta_detalle_medicamento_xor",
        ),
        Index("ix_receta_detalle_receta", "id_receta", "posicion"),
    )

    receta = relationship("Receta", back_populates="detalles")
    medicamento = relationship("Medicamento", lazy="joined")

    def __repr__(self) -> str:
        return f"<RecetaDetalle(id={self.id_receta_detalle}, receta={self.id_receta}, pos={self.posicion})>"


class ConfiguracionRecetas(Base):
    """Vigencia máxima por clínica (ausencia de fila equivale a 90 días)."""

    __tablename__ = "configuracion_recetas"

    id_clinica = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("clinicas.id_clinica"), primary_key=True)
    vigencia_maxima_dias = Column(SmallInteger, nullable=False, default=90)

    __table_args__ = (
        CheckConstraint("vigencia_maxima_dias BETWEEN 1 AND 90", name="ck_config_recetas_vigencia"),
    )

    def __repr__(self) -> str:
        return f"<ConfiguracionRecetas(clinica={self.id_clinica}, max_dias={self.vigencia_maxima_dias})>"


class SecuenciaRecetas(Base):
    """Contador atómico de folios por (clínica, año)."""

    __tablename__ = "secuencias_recetas"

    id_clinica = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("clinicas.id_clinica"), primary_key=True)
    anio = Column(Integer, primary_key=True)
    ultimo_numero = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<SecuenciaRecetas(clinica={self.id_clinica}, anio={self.anio}, ultimo={self.ultimo_numero})>"


class RecetaIdempotencia(Base):
    """Claves de idempotencia hasheadas con vigencia de 24 horas."""

    __tablename__ = "receta_idempotencia"

    id_receta_idempotencia = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id_clinica = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("clinicas.id_clinica"), nullable=False)
    id_usuario = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("usuarios.id_usuario"), nullable=False)
    clave_hash = Column(CHAR(64), nullable=False)
    request_hash = Column(Text, nullable=False)
    id_receta = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("recetas.id_receta", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("id_clinica", "id_usuario", "clave_hash", name="uq_receta_idempotencia_clave"),
        Index("ix_receta_idempotencia_expira", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<RecetaIdempotencia(clinica={self.id_clinica}, usuario={self.id_usuario}, receta={self.id_receta})>"


class RecetaValidacionIntento(Base):
    """Telemetría anonimizada y rate limiting de validación pública (retención 30 días)."""

    __tablename__ = "receta_validacion_intentos"

    id_validacion_intento = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    codigo_hash = Column(CHAR(64), nullable=False)
    ip_hash = Column(CHAR(64), nullable=False)
    resultado = Column(String(30), nullable=False)
    fecha_hora = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_validacion_codigo_ventana", "codigo_hash", "fecha_hora"),
        Index("ix_validacion_ip_ventana", "ip_hash", "fecha_hora"),
    )

    def __repr__(self) -> str:
        return f"<RecetaValidacionIntento(codigo_hash=..., resultado='{self.resultado}')>"
