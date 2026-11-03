"""Persistencia de avisos y dispositivos del seguimiento terapéutico CU17."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func,
)

from app.core.database import Base


_id = BigInteger().with_variant(Integer, "sqlite")


class TratamientoAviso(Base):
    __tablename__ = "tratamiento_avisos"

    id_aviso = Column(_id, primary_key=True, autoincrement=True)
    id_clinica = Column(_id, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_tratamiento = Column(_id, ForeignKey("tratamientos.id_tratamiento"), nullable=False)
    id_dosis = Column(_id, ForeignKey("tratamiento_dosis.id_dosis"), nullable=False)
    id_usuario = Column(_id, ForeignKey("usuarios.id_usuario"), nullable=False)
    tipo = Column(String(30), nullable=False)
    canal = Column(String(10), nullable=False)
    titulo = Column(String(200), nullable=False)
    mensaje = Column(Text, nullable=False)
    programada_en_utc = Column(DateTime(timezone=True), nullable=False)
    estado = Column(String(15), nullable=False, default="PENDIENTE")
    enviada_en_utc = Column(DateTime(timezone=True))
    leida_en_utc = Column(DateTime(timezone=True))
    intentos = Column(Integer, nullable=False, default=0)
    ultimo_error = Column(String(100))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("id_clinica", "id_dosis", "id_usuario", "tipo", "canal", name="uq_cu17_aviso"),
        CheckConstraint("tipo IN ('RECORDATORIO','OMISION','RIESGO_ABANDONO')", name="ck_cu17_aviso_tipo"),
        CheckConstraint("canal IN ('WEB','PUSH')", name="ck_cu17_aviso_canal"),
        CheckConstraint("estado IN ('PENDIENTE','ENVIADO','FALLIDO')", name="ck_cu17_aviso_estado"),
        Index("ix_cu17_aviso_usuario", "id_clinica", "id_usuario", "canal", "created_at"),
        Index("ix_cu17_aviso_pendiente", "id_clinica", "canal", "estado", "programada_en_utc"),
    )


class TratamientoDispositivo(Base):
    __tablename__ = "tratamiento_dispositivos"

    id_dispositivo = Column(_id, primary_key=True, autoincrement=True)
    id_clinica = Column(_id, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_usuario = Column(_id, ForeignKey("usuarios.id_usuario"), nullable=False)
    token_cifrado = Column(Text, nullable=False)
    token_hash = Column(String(64), nullable=False)
    plataforma = Column(String(10), nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("id_clinica", "id_usuario", "token_hash", name="uq_cu17_dispositivo"),
        CheckConstraint("plataforma IN ('ANDROID','IOS')", name="ck_cu17_dispositivo_plataforma"),
        Index("ix_cu17_dispositivo_usuario", "id_clinica", "id_usuario", "activo"),
    )


class TratamientoEntregaPush(Base):
    """Estado por dispositivo para evitar reenviar a los ya confirmados."""
    __tablename__ = "tratamiento_entregas_push"

    id_entrega = Column(_id, primary_key=True, autoincrement=True)
    id_clinica = Column(_id, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_aviso = Column(_id, ForeignKey("tratamiento_avisos.id_aviso"), nullable=False)
    id_dispositivo = Column(_id, ForeignKey("tratamiento_dispositivos.id_dispositivo"), nullable=False)
    estado = Column(String(15), nullable=False, default="PENDIENTE")
    intentos = Column(Integer, nullable=False, default=0)
    proximo_intento_en_utc = Column(DateTime(timezone=True))
    ultimo_error = Column(String(100))
    enviada_en_utc = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("id_clinica", "id_aviso", "id_dispositivo", name="uq_cu17_entrega_push"),
        CheckConstraint("estado IN ('PENDIENTE','ENVIADO','FALLIDO')", name="ck_cu17_entrega_estado"),
        Index("ix_cu17_entrega_pendiente", "id_clinica", "estado", "proximo_intento_en_utc"),
    )


class TratamientoCursor(Base):
    """Día local pendiente de materialización histórica por tratamiento."""
    __tablename__ = "tratamiento_cursores"

    id_clinica = Column(_id, ForeignKey("clinicas.id_clinica"), primary_key=True)
    id_tratamiento = Column(_id, ForeignKey("tratamientos.id_tratamiento"), primary_key=True)
    siguiente_fecha = Column(Date, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
