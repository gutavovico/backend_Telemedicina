"""Modelos ORM de CU29 — Vinculación de médicos con entidades.

La identidad profesional (`Usuario`/`Medico`) es global; la participación en
cada entidad se representa con `vinculaciones_medico_entidad`. Solo el vínculo
en estado `ACTIVO` concede acceso operativo a la entidad.
"""
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base

ESTADOS_VINCULACION = ("INVITADO", "ACTIVO", "SUSPENDIDO", "RECHAZADO", "BAJA")
TIPOS_EVENTO_HISTORIAL = ("CREACION", "RESPUESTA_INVITACION", "ASIGNACIONES", "CAMBIO_ESTADO")

_ID_BIGINT = BigInteger().with_variant(Integer, "sqlite")
_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class VinculacionMedicoEntidad(Base):
    __tablename__ = "vinculaciones_medico_entidad"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('INVITADO','ACTIVO','SUSPENDIDO','RECHAZADO','BAJA')",
            name="ck_vinculacion_estado",
        ),
        UniqueConstraint("id_clinica", "id_usuario", name="uq_vinculacion_clinica_usuario"),
        UniqueConstraint("id_clinica", "id_medico", name="uq_vinculacion_clinica_medico"),
        Index("ix_vinculacion_clinica_estado", "id_clinica", "estado"),
    )

    id_vinculacion = Column(_ID_BIGINT, primary_key=True, autoincrement=True)
    id_clinica = Column(
        BigInteger,
        ForeignKey("clinicas.id_clinica", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_usuario = Column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_medico = Column(
        BigInteger,
        ForeignKey("medicos.id_medico", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    estado = Column(String(20), nullable=False, default="INVITADO", server_default="INVITADO")
    invitado_por = Column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"),
        nullable=True,
    )
    fecha_invitacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    respondido_en = Column(DateTime(timezone=True), nullable=True)
    fecha_estado = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    usuario_estado = Column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"),
        nullable=True,
    )
    motivo_estado = Column(Text, nullable=True)
    row_version = Column(Integer, nullable=False, default=1, server_default="1")

    roles = relationship(
        "VinculacionMedicoRol",
        back_populates="vinculacion",
        cascade="all, delete-orphan",
    )
    especialidades = relationship(
        "VinculacionMedicoEspecialidad",
        back_populates="vinculacion",
        cascade="all, delete-orphan",
    )
    sedes = relationship(
        "VinculacionMedicoSede",
        back_populates="vinculacion",
        cascade="all, delete-orphan",
    )
    historial = relationship(
        "HistorialVinculacionMedico",
        back_populates="vinculacion",
    )

    def __repr__(self) -> str:
        return (
            f"<VinculacionMedicoEntidad(id={self.id_vinculacion}, "
            f"clinica={self.id_clinica}, usuario={self.id_usuario}, estado='{self.estado}')>"
        )


class VinculacionMedicoRol(Base):
    __tablename__ = "vinculacion_medico_rol"
    __table_args__ = (
        Index(
            "uq_vinculacion_medico_rol_principal",
            "id_vinculacion",
            unique=True,
            postgresql_where=text("es_principal = TRUE"),
            sqlite_where=text("es_principal = 1"),
        ),
    )

    id_vinculacion = Column(
        BigInteger,
        ForeignKey("vinculaciones_medico_entidad.id_vinculacion", ondelete="CASCADE"),
        primary_key=True,
    )
    id_rol = Column(
        BigInteger,
        ForeignKey("roles.id_rol", ondelete="RESTRICT"),
        primary_key=True,
    )
    es_principal = Column(Boolean, nullable=False, default=False, server_default=text("FALSE"))

    vinculacion = relationship("VinculacionMedicoEntidad", back_populates="roles")

    def __repr__(self) -> str:
        return (
            f"<VinculacionMedicoRol(id_vinculacion={self.id_vinculacion}, "
            f"id_rol={self.id_rol}, principal={self.es_principal})>"
        )


class VinculacionMedicoEspecialidad(Base):
    __tablename__ = "vinculacion_medico_especialidad"
    __table_args__ = (
        Index(
            "uq_vinculacion_medico_especialidad_principal",
            "id_vinculacion",
            unique=True,
            postgresql_where=text("es_principal = TRUE"),
            sqlite_where=text("es_principal = 1"),
        ),
    )

    id_vinculacion = Column(
        BigInteger,
        ForeignKey("vinculaciones_medico_entidad.id_vinculacion", ondelete="CASCADE"),
        primary_key=True,
    )
    id_especialidad = Column(
        BigInteger,
        ForeignKey("especialidades.id_especialidad", ondelete="RESTRICT"),
        primary_key=True,
    )
    es_principal = Column(Boolean, nullable=False, default=False, server_default=text("FALSE"))

    vinculacion = relationship("VinculacionMedicoEntidad", back_populates="especialidades")

    def __repr__(self) -> str:
        return (
            f"<VinculacionMedicoEspecialidad(id_vinculacion={self.id_vinculacion}, "
            f"id_especialidad={self.id_especialidad}, principal={self.es_principal})>"
        )


class VinculacionMedicoSede(Base):
    """Sede de CU33 asignada a un vínculo médico-entidad.

    La tabla depende del catálogo `sedes` de CU33; la revisión Alembic de CU29
    que la crea cuelga del head que incluye CU33.
    """

    __tablename__ = "vinculacion_medico_sede"

    id_vinculacion = Column(
        BigInteger,
        ForeignKey("vinculaciones_medico_entidad.id_vinculacion", ondelete="CASCADE"),
        primary_key=True,
    )
    id_sede = Column(
        BigInteger,
        ForeignKey("sedes.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )

    vinculacion = relationship("VinculacionMedicoEntidad", back_populates="sedes")

    def __repr__(self) -> str:
        return (
            f"<VinculacionMedicoSede(id_vinculacion={self.id_vinculacion}, "
            f"id_sede={self.id_sede})>"
        )


class HistorialVinculacionMedico(Base):
    __tablename__ = "historial_vinculaciones_medico"
    __table_args__ = (
        CheckConstraint(
            "tipo_evento IN ('CREACION','RESPUESTA_INVITACION','ASIGNACIONES','CAMBIO_ESTADO')",
            name="ck_historial_vinculacion_tipo",
        ),
    )

    id_historial = Column(_ID_BIGINT, primary_key=True, autoincrement=True)
    id_vinculacion = Column(
        BigInteger,
        ForeignKey("vinculaciones_medico_entidad.id_vinculacion", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    tipo_evento = Column(String(30), nullable=False)
    estado_anterior = Column(String(20), nullable=True)
    estado_nuevo = Column(String(20), nullable=True)
    id_usuario_actor = Column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"),
        nullable=False,
    )
    motivo = Column(Text, nullable=True)
    datos = Column(_JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'"))
    fecha_cambio = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    vinculacion = relationship("VinculacionMedicoEntidad", back_populates="historial")

    def __repr__(self) -> str:
        return (
            f"<HistorialVinculacionMedico(id={self.id_historial}, "
            f"vinculacion={self.id_vinculacion}, tipo='{self.tipo_evento}')>"
        )


class CredencialTemporalMedico(Base):
    __tablename__ = "credenciales_temporarias_medico"
    __table_args__ = (
        UniqueConstraint("id_usuario", name="uq_credencial_temporal_usuario"),
    )

    id_credencial = Column(_ID_BIGINT, primary_key=True, autoincrement=True)
    id_usuario = Column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="CASCADE"),
        nullable=False,
    )
    id_vinculacion = Column(
        BigInteger,
        ForeignKey("vinculaciones_medico_entidad.id_vinculacion", ondelete="CASCADE"),
        nullable=False,
    )
    expira_en = Column(DateTime(timezone=True), nullable=False)
    usada_en = Column(DateTime(timezone=True), nullable=True)
    cambiada_en = Column(DateTime(timezone=True), nullable=True)
    row_version = Column(Integer, nullable=False, default=1, server_default="1")

    vinculacion = relationship("VinculacionMedicoEntidad", foreign_keys=[id_vinculacion])

    def __repr__(self) -> str:
        return (
            f"<CredencialTemporalMedico(id={self.id_credencial}, "
            f"usuario={self.id_usuario}, usada={self.usada_en is not None})>"
        )


__all__ = [
    "ESTADOS_VINCULACION",
    "TIPOS_EVENTO_HISTORIAL",
    "VinculacionMedicoEntidad",
    "VinculacionMedicoRol",
    "VinculacionMedicoEspecialidad",
    "VinculacionMedicoSede",
    "HistorialVinculacionMedico",
    "CredencialTemporalMedico",
]
