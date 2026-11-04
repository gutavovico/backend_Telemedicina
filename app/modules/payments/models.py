"""Modelos de persistencia para CU19 (pagos y comprobantes).

Se mantienen los nombres y columnas documentados en el esquema del proyecto
(`pagos` y `comprobantes`) y se añaden los campos propios de la integración con
Stripe Checkout y del QR de pago.
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Pago(Base):
    __tablename__ = "pagos"

    id_pago = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    id_usuario = Column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    id_cita = Column(
        BigInteger,
        ForeignKey("citas.id_cita", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    id_clinica = Column(
        BigInteger,
        ForeignKey("clinicas.id_clinica", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    monto = Column(Numeric(12, 2), nullable=False)
    moneda = Column(String(10), nullable=False, default="BOB", server_default="BOB")
    metodo_pago = Column(String(50), nullable=True)          # TARJETA | QR
    pasarela = Column(String(100), nullable=True)            # STRIPE
    referencia_transaccion = Column(String(200), nullable=True)
    fecha_pago = Column(DateTime(timezone=False), nullable=True)
    estado = Column(
        String(30),
        nullable=False,
        default="PENDIENTE",
        server_default="PENDIENTE",
        index=True,
    )

    # Integración Stripe Checkout / QR (CU19)
    stripe_session_id = Column(String(255), nullable=True, unique=True, index=True)
    stripe_payment_intent_id = Column(String(255), nullable=True, index=True)
    url_checkout = Column(String(1000), nullable=True)
    qr_token = Column(String(64), nullable=True, unique=True, index=True)
    expira_en = Column(DateTime(timezone=False), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    cita = relationship("Cita", backref="pagos")
    usuario = relationship("Usuario")
    comprobante = relationship(
        "Comprobante",
        back_populates="pago",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Pago(id={self.id_pago}, cita={self.id_cita}, monto={self.monto}, "
            f"estado='{self.estado}')>"
        )


class Comprobante(Base):
    __tablename__ = "comprobantes"

    id_comprobante = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    id_pago = Column(
        BigInteger,
        ForeignKey("pagos.id_pago", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    numero_comprobante = Column(String(50), nullable=False, unique=True, index=True)
    tipo_comprobante = Column(
        String(30), nullable=False, default="RECIBO", server_default="RECIBO"
    )
    fecha_emision = Column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    archivo_url = Column(String(500), nullable=True)
    estado = Column(
        String(20), nullable=False, default="EMITIDO", server_default="EMITIDO"
    )

    pago = relationship("Pago", back_populates="comprobante")

    def __repr__(self) -> str:
        return (
            f"<Comprobante(id={self.id_comprobante}, numero='{self.numero_comprobante}', "
            f"estado='{self.estado}')>"
        )
