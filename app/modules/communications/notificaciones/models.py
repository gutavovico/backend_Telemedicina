"""Modelos SQLAlchemy 2.0 para CU20: Dispositivos Autorizados, Outbox Transaccional y Bandeja."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base
from app.modules.communications.models import Notificacion

_id_type = BigInteger().with_variant(Integer, "sqlite")


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


class DispositivoAutorizado(Base):
    """Dispositivos Web (PWA) y Móvil (FLUTTER) registrados por usuario para entrega Push."""

    __tablename__ = "dispositivos_autorizados"
    __table_args__ = (
        UniqueConstraint(
            "id_usuario", "canal", "dispositivo_id", name="uq_disp_usr_canal_cu20"
        ),
        CheckConstraint("canal IN ('PWA', 'FLUTTER')", name="ck_disp_canal_cu20"),
        CheckConstraint("estado IN ('ACTIVO', 'REVOCADO')", name="ck_disp_estado_cu20"),
        Index("ix_dispositivos_usuario_activo", "id_usuario", "estado"),
        Index("ix_dispositivos_clinica_usuario", "id_clinica", "id_usuario"),
    )

    id_dispositivo = Column(_id_type, primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=True, index=True)
    id_usuario = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False, index=True)
    rol_usuario = Column(String(30), nullable=True)
    canal = Column(String(12), nullable=False)  # 'PWA' | 'FLUTTER'
    dispositivo_id = Column(String(64), nullable=False)
    push_destino_cifrado = Column(LargeBinary, nullable=True)
    push_destino_hash = Column(String(64), nullable=True)
    estado = Column(String(16), nullable=False, default="ACTIVO")  # 'ACTIVO' | 'REVOCADO'
    revision = Column(Integer, nullable=False, default=1)
    creado_en = Column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    revocado_en = Column(DateTime(timezone=True), nullable=True)


class EventoOutbox(Base):
    """Cola Outbox Transaccional para entrega multicanal confiable con deduplicación y reintentos."""

    __tablename__ = "eventos_outbox"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('PENDIENTE', 'REINTENTO', 'ENVIADO', 'FALLIDO', 'FALLIDO_PARCIAL', 'SIN_DESTINOS')",
            name="ck_outbox_estado_cu20",
        ),
        Index("ix_outbox_pendiente", "estado", "proximo_intento_en", "creado_en"),
        Index("ix_outbox_idempotencia", "idempotency_hash"),
        Index("ix_outbox_clinica", "id_clinica", "estado"),
    )

    id_evento = Column(_id_type, primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=True, index=True)
    id_usuario_destino = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False, index=True)
    recurso_tipo = Column(String(50), nullable=False)
    recurso_id = Column(String(64), nullable=False)
    transicion = Column(String(60), nullable=False)
    canal_objetivo = Column(String(20), nullable=False, default="MULTI")  # MULTI | PUSH | EMAIL | SMS
    revision = Column(Integer, nullable=False, default=1)
    dispositivo_id = Column(String(64), nullable=True)
    idempotency_hash = Column(String(64), nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    estado = Column(String(20), nullable=False, default="PENDIENTE")
    intentos = Column(Integer, nullable=False, default=0)
    max_intentos = Column(Integer, nullable=False, default=3)
    ultimo_error = Column(Text, nullable=True)
    proximo_intento_en = Column(DateTime(timezone=True), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    entregado_en = Column(DateTime(timezone=True), nullable=True)


__all__ = ["DispositivoAutorizado", "EventoOutbox", "Notificacion"]
