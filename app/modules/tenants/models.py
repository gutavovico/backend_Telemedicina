import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class TenantRequest(Base):
    __tablename__ = "tenant_requests"

    id_request = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institucion_nombre = Column(String(150), nullable=False)
    razon_social = Column(String(200), nullable=True)
    nit = Column(String(50), nullable=False, index=True)
    correo = Column(String(150), nullable=False)
    telefono = Column(String(30), nullable=True)
    direccion = Column(String(250), nullable=True)

    responsable_nombre = Column(String(150), nullable=False)
    responsable_correo = Column(String(150), nullable=False)
    responsable_telefono = Column(String(30), nullable=True)

    # Referencia canónica CU34; ``plan_version_id`` se conserva para lectura legacy.
    id_version_plan = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("versiones_plan.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    plan_version_id = Column(String(36), nullable=True)
    documentos_metadata = Column(Text, nullable=True)  # JSON serializado con nombre, mime, sha256, path
    tracking_code = Column(String(64), unique=True, index=True, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, APPROVED, REJECTED
    # Trazabilidad de seguridad del portal público (nunca se expone en tracking).
    correlation_id = Column(String(64), nullable=True, index=True)
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)

    decision_motivo = Column(Text, nullable=True)
    decision_fecha = Column(DateTime(timezone=True), nullable=True)
    tenant_id = Column(String(36), nullable=True)
    id_clinica = Column(BigInteger, nullable=True)
    # Credencial temporal de acceso. Se cifra y solo se revela en la ventana de
    # seguridad; el hash normal del usuario sigue siendo la credencial de login.
    temporary_password_encrypted = Column(Text, nullable=True)
    temporary_password_expires_at = Column(DateTime(timezone=True), nullable=True)
    temporary_password_reveal_count = Column(Integer, nullable=False, default=0, server_default="0")
    temporary_password_used_at = Column(DateTime(timezone=True), nullable=True)
    temporary_password_changed_at = Column(DateTime(timezone=True), nullable=True)
    credentials_issued = Column(Boolean, nullable=False, default=False, server_default="0")
    row_version = Column(Integer, nullable=False, default=1, server_default="1")
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TenantRequestTrackingAudit(Base):
    """Auditoría anónima de consultas y revelaciones de credenciales temporales."""

    __tablename__ = "tenant_request_tracking_audits"

    id_audit = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_request = Column(String(36), nullable=True, index=True)
    tracking_code_hash = Column(String(64), nullable=False, index=True)
    accion = Column(String(50), nullable=False)
    resultado = Column(String(30), nullable=False)
    direccion_ip = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    fecha_hora = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TenantDeactivationRequest(Base):
    __tablename__ = "tenant_deactivation_requests"

    id_deactivation = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=True)
    motivo = Column(Text, nullable=False)
    solicitante_id = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, APPROVED, REJECTED, CANCELLED
    decision_motivo = Column(Text, nullable=True)
    decision_fecha = Column(DateTime(timezone=True), nullable=True)
    decidido_por = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=True)
    row_version = Column(Integer, nullable=False, default=1, server_default="1")
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlanVersion(Base):
    __tablename__ = "plan_versions"

    id_plan_version = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    precio_mensual = Column(Numeric(10, 2), nullable=False, default=0, server_default="0")
    precio_anual = Column(Numeric(10, 2), nullable=False, default=0, server_default="0")
    moneda = Column(String(10), nullable=False, default="BOB", server_default="BOB")
    limite_medicos = Column(Integer, nullable=False, default=10, server_default="10")
    limite_consultas_mes = Column(Integer, nullable=False, default=100, server_default="100")
    estado = Column(String(20), nullable=False, default="ACTIVO", server_default="ACTIVO")  # ACTIVO, INACTIVO
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"

    id_suscripcion = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=False, unique=True, index=True)
    tenant_id = Column(String(36), nullable=True)
    # Referencia canónica CU34. El UUID legacy se conserva únicamente para
    # trazabilidad durante la transición Expand -> Backfill -> Contract.
    id_version_plan = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("versiones_plan.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    id_plan_version = Column(String(36), ForeignKey("plan_versions.id_plan_version"), nullable=True)
    ciclo = Column(String(20), nullable=False, default="MONTHLY", server_default="MONTHLY")
    fecha_inicio = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_fin = Column(DateTime(timezone=True), nullable=False)
    dias_gracia = Column(Integer, nullable=False, default=7, server_default="7")
    estado = Column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")  # TRIALING, ACTIVE, PAST_DUE, EXPIRED, CANCELLED
    row_version = Column(Integer, nullable=False, default=1, server_default="1")
    fecha_actualizacion = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    plan = relationship("PlanVersion")
    plan_canonico = relationship("VersionPlan", foreign_keys=[id_version_plan])
    clinica = relationship("Clinica")


class SubscriptionPayment(Base):
    __tablename__ = "subscription_payments"

    id_pago_suscripcion = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    id_suscripcion = Column(String(36), ForeignKey("tenant_subscriptions.id_suscripcion"), nullable=False, index=True)
    id_clinica = Column(BigInteger, ForeignKey("clinicas.id_clinica"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=True)
    id_usuario = Column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    id_version_plan = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("versiones_plan.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    id_plan_version = Column(String(36), ForeignKey("plan_versions.id_plan_version"), nullable=True)
    ciclo = Column(String(20), nullable=False)
    monto = Column(Numeric(10, 2), nullable=False)
    moneda = Column(String(10), nullable=False, default="BOB", server_default="BOB")
    estado = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")  # PENDING, PAGADO, FALLIDO, CANCELADO
    stripe_session_id = Column(String(255), unique=True, nullable=True, index=True)
    stripe_payment_intent_id = Column(String(255), nullable=True)
    url_checkout = Column(String(1000), nullable=True)
    expira_en = Column(DateTime(timezone=True), nullable=True)
    numero_factura = Column(String(50), unique=True, nullable=True)
    fecha_pago = Column(DateTime(timezone=True), nullable=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    suscripcion = relationship("TenantSubscription")
    plan = relationship("PlanVersion")
    plan_canonico = relationship("VersionPlan", foreign_keys=[id_version_plan])
