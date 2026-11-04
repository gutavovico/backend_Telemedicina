import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.tenant_status import CANONICAL_ACTIVE, canonical_tenant_status
from app.modules.auth.models import Clinica, Usuario
from app.modules.payments.service import (
    _stripe_request,
    stripe_habilitado,
    verificar_firma_stripe,
)
from app.modules.tenants.models import PlanVersion, SubscriptionPayment, TenantSubscription
from .schemas import (
    CheckoutResponse,
    CurrentSubscriptionResponse,
    PlanVersionItem,
    ReceiptMetadataResponse,
    SubscriptionPaymentHistoryResponse,
    SubscriptionPaymentItem,
)


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _webhook_secret() -> str:
    try:
        return settings.STRIPE_WEBHOOK_SECRET.get_secret_value().strip()
    except Exception:
        return str(settings.STRIPE_WEBHOOK_SECRET or "").strip()


def _url_con_pago(url: str, id_pago: str) -> str:
    separador = "&" if "?" in url else "?"
    return f"{url}{separador}pago={id_pago}"


def _crear_sesion_stripe(
    plan: PlanVersion,
    pago: SubscriptionPayment,
    monto: float,
    ciclo: str,
) -> dict:
    amount = int(round(monto * 100))
    return _stripe_request(
        "POST",
        "/v1/checkout/sessions",
        data={
            "mode": "payment",
            "line_items[0][quantity]": 1,
            "line_items[0][price_data][currency]": (plan.moneda or settings.STRIPE_CURRENCY).lower(),
            "line_items[0][price_data][unit_amount]": amount,
            "line_items[0][price_data][product_data][name]": f"Suscripción {plan.nombre} ({ciclo})",
            "line_items[0][price_data][product_data][description]": "Pago de suscripción de plataforma",
            "success_url": _url_con_pago(settings.SUBSCRIPTION_WEB_SUCCESS_URL, pago.id_pago_suscripcion),
            "cancel_url": settings.SUBSCRIPTION_WEB_CANCEL_URL,
            "client_reference_id": f"suscripcion-{pago.id_pago_suscripcion}",
            "locale": "es",
            "metadata[id_pago_suscripcion]": pago.id_pago_suscripcion,
            "metadata[tenant_id]": pago.id_clinica,
            "metadata[tipo]": "suscripcion",
        },
    )


def _extender_vigencia(sub: TenantSubscription, ciclo: str) -> None:
    """Extiende el período sin perder días ya pagados."""
    ahora = datetime.now(timezone.utc)
    dias = 365 if ciclo == "ANNUAL" else 30
    fin_actual = _to_utc(sub.fecha_fin)
    if (
        fin_actual is not None
        and fin_actual > ahora
        and canonical_tenant_status(sub.estado) == CANONICAL_ACTIVE
    ):
        # El nuevo período arranca el día siguiente al vencimiento vigente.
        sub.fecha_inicio = fin_actual + timedelta(days=1)
        sub.fecha_fin = sub.fecha_inicio + timedelta(days=dias - 1)
    else:
        sub.fecha_inicio = ahora
        sub.fecha_fin = ahora + timedelta(days=dias)
    sub.ciclo = ciclo
    sub.estado = "ACTIVE"
    sub.row_version += 1


def get_current_subscription(db: Session, tenant_id: int) -> CurrentSubscriptionResponse:
    sub = db.query(TenantSubscription).filter(TenantSubscription.id_clinica == tenant_id).first()
    if not sub:
        return CurrentSubscriptionResponse(has_subscription=False)

    ahora = datetime.now(timezone.utc)
    fin = _to_utc(sub.fecha_fin) or ahora
    gracia = sub.dias_gracia or 7

    if fin < ahora:
        if ahora <= fin + timedelta(days=gracia):
            derived = "DUE_SOON"
        else:
            derived = "EXPIRED"
    else:
        if fin - ahora <= timedelta(days=5):
            derived = "DUE_SOON"
        else:
            derived = "ACTIVE"

    plan = sub.plan
    return CurrentSubscriptionResponse(
        has_subscription=True,
        id_suscripcion=sub.id_suscripcion,
        tenant_id=sub.tenant_id or str(sub.id_clinica),
        plan_nombre=plan.nombre if plan else "Plan Base",
        plan_version_id=sub.id_plan_version,
        ciclo=sub.ciclo,
        fecha_inicio=sub.fecha_inicio,
        fecha_fin=sub.fecha_fin,
        dias_gracia=sub.dias_gracia,
        estado=sub.estado,
        derived_status=derived,
        limite_medicos=plan.limite_medicos if plan else 10,
        limite_consultas_mes=plan.limite_consultas_mes if plan else 100,
    )


def list_active_plans(db: Session) -> List[PlanVersionItem]:
    planes = (
        db.query(PlanVersion)
        .filter(PlanVersion.estado == "ACTIVO")
        .order_by(PlanVersion.precio_mensual.asc())
        .all()
    )
    return [
        PlanVersionItem(
            id_plan_version=p.id_plan_version,
            nombre=p.nombre,
            descripcion=p.descripcion,
            precio_mensual=float(p.precio_mensual),
            precio_anual=float(p.precio_anual),
            moneda=p.moneda,
            limite_medicos=p.limite_medicos,
            limite_consultas_mes=p.limite_consultas_mes,
        )
        for p in planes
    ]


def create_subscription_checkout(
    db: Session,
    tenant_id: int,
    user: Usuario,
    plan_version_id: str,
    cycle: str,
) -> CheckoutResponse:
    plan = (
        db.query(PlanVersion)
        .filter(PlanVersion.id_plan_version == plan_version_id, PlanVersion.estado == "ACTIVO")
        .first()
    )
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La versión de plan solicitada no existe o no está activa",
        )

    # Determinar precio autoritativo desde la base de datos
    monto = float(plan.precio_anual if cycle.upper() == "ANNUAL" else plan.precio_mensual)

    # Reutilizar checkout activo pendiente en vez de duplicar
    ahora = datetime.now(timezone.utc)
    hace_veinte_minutos = ahora - timedelta(minutes=20)
    pago_existente = (
        db.query(SubscriptionPayment)
        .filter(
            SubscriptionPayment.id_clinica == tenant_id,
            SubscriptionPayment.id_plan_version == plan_version_id,
            SubscriptionPayment.ciclo == cycle.upper(),
            SubscriptionPayment.estado == "PENDING",
            SubscriptionPayment.fecha_creacion >= hace_veinte_minutos,
        )
        .first()
    )
    if pago_existente and pago_existente.url_checkout:
        return CheckoutResponse(
            id_pago=pago_existente.id_pago_suscripcion,
            monto=float(pago_existente.monto),
            moneda=pago_existente.moneda,
            checkout_url=pago_existente.url_checkout,
            expira_en=pago_existente.expira_en,
        )

    # Crear suscripción o referencia
    sub = db.query(TenantSubscription).filter(TenantSubscription.id_clinica == tenant_id).first()
    if not sub:
        sub = TenantSubscription(
            id_clinica=tenant_id,
            id_plan_version=plan_version_id,
            ciclo=cycle.upper(),
            fecha_inicio=ahora,
            fecha_fin=ahora,
            estado="TRIALING",
            row_version=1,
        )
        db.add(sub)
        db.flush()

    expira_en = ahora + timedelta(hours=2)
    nuevo_pago = SubscriptionPayment(
        id_suscripcion=sub.id_suscripcion,
        id_clinica=tenant_id,
        id_usuario=user.id_usuario,
        id_plan_version=plan_version_id,
        ciclo=cycle.upper(),
        monto=monto,
        moneda=plan.moneda or "BOB",
        estado="PENDING",
        expira_en=expira_en,
    )
    db.add(nuevo_pago)
    db.flush()

    if stripe_habilitado():
        sesion = _crear_sesion_stripe(plan, nuevo_pago, monto, cycle.upper())
        session_id = sesion.get("id") or f"cs_sub_{uuid.uuid4().hex}"
        checkout_url = sesion.get("url") or ""
        if not checkout_url:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Stripe no devolvió una URL de checkout válida",
            )
    else:
        # Modo simulado (sin credenciales): nunca confirma el pago por sí solo.
        session_id = f"cs_sub_{uuid.uuid4().hex}"
        checkout_url = _url_con_pago(
            f"{settings.SUBSCRIPTION_WEB_SUCCESS_URL.split('?')[0]}?checkout=simulated&session_id={session_id}",
            nuevo_pago.id_pago_suscripcion,
        )

    nuevo_pago.stripe_session_id = session_id
    nuevo_pago.url_checkout = checkout_url
    db.commit()
    db.refresh(nuevo_pago)

    return CheckoutResponse(
        id_pago=nuevo_pago.id_pago_suscripcion,
        monto=monto,
        moneda=nuevo_pago.moneda,
        checkout_url=checkout_url,
        expira_en=expira_en,
    )


def confirm_subscription_payment(
    db: Session,
    stripe_session_id_or_payment_id: str,
) -> SubscriptionPayment:
    pago = (
        db.query(SubscriptionPayment)
        .filter(
            (SubscriptionPayment.stripe_session_id == stripe_session_id_or_payment_id)
            | (SubscriptionPayment.id_pago_suscripcion == stripe_session_id_or_payment_id)
        )
        .first()
    )
    if not pago:
        raise HTTPException(status_code=404, detail="Pago de suscripción no encontrado")

    # Idempotencia: si ya está pagado, no volver a extender
    if pago.estado == "PAGADO":
        return pago

    pago.estado = "PAGADO"
    pago.fecha_pago = datetime.now(timezone.utc)
    if not pago.numero_factura:
        pago.numero_factura = f"FAC-SUB-{uuid.uuid4().hex[:8].upper()}"

    # Extender período de suscripción respetando el tiempo restante
    sub = db.query(TenantSubscription).filter(TenantSubscription.id_clinica == pago.id_clinica).first()
    if sub:
        sub.id_plan_version = pago.id_plan_version
        _extender_vigencia(sub, pago.ciclo)

    db.commit()
    db.refresh(pago)
    return pago


def sincronizar_checkout_suscripcion(
    db: Session,
    tenant_id: int,
    id_pago: str,
) -> SubscriptionPayment:
    """Consulta el estado real en Stripe y confirma si el pago ya se completó."""
    pago = (
        db.query(SubscriptionPayment)
        .filter(
            SubscriptionPayment.id_pago_suscripcion == id_pago,
            SubscriptionPayment.id_clinica == tenant_id,
        )
        .first()
    )
    if not pago:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pago de suscripción no encontrado para este tenant",
        )

    if pago.estado == "PAGADO" or not stripe_habilitado() or not pago.stripe_session_id:
        return pago

    try:
        sesion = _stripe_request("GET", f"/v1/checkout/sessions/{pago.stripe_session_id}")
    except Exception:
        # La consulta a la pasarela no debe otorgar vigencia por sí sola.
        return pago

    if sesion.get("payment_status") == "paid":
        return confirm_subscription_payment(db, pago.stripe_session_id)
    return pago


def procesar_webhook_suscripcion(
    db: Session,
    payload: bytes,
    signature_header: str,
) -> dict:
    """Webhook Stripe firmado e idempotente para suscripciones (CU31)."""
    verificar_firma_stripe(payload, signature_header, _webhook_secret())

    try:
        evento = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cuerpo de webhook inválido",
        ) from exc

    tipo = evento.get("type") or ""
    sesion = (evento.get("data") or {}).get("object") or {}
    metadata = sesion.get("metadata") or {}
    id_pago = metadata.get("id_pago_suscripcion")
    session_id = sesion.get("id")

    pago = None
    if id_pago:
        pago = (
            db.query(SubscriptionPayment)
            .filter(SubscriptionPayment.id_pago_suscripcion == id_pago)
            .first()
        )
    if pago is None and session_id:
        pago = (
            db.query(SubscriptionPayment)
            .filter(SubscriptionPayment.stripe_session_id == session_id)
            .first()
        )

    if pago is None:
        return {"received": True, "ignored": tipo, "motivo": "pago no encontrado"}

    if tipo in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        pago = confirm_subscription_payment(db, pago.id_pago_suscripcion)
        return {"received": True, "id_pago": pago.id_pago_suscripcion, "estado": pago.estado}

    if tipo == "checkout.session.expired" and pago.estado == "PENDING":
        pago.estado = "CANCELADO"
        db.commit()
    elif tipo in ("checkout.session.async_payment_failed", "payment_intent.payment_failed"):
        if pago.estado == "PENDING":
            pago.estado = "FALLIDO"
            db.commit()

    return {"received": True, "id_pago": pago.id_pago_suscripcion, "estado": pago.estado}


def list_subscription_payments(
    db: Session,
    tenant_id: int,
    page: int = 1,
    per_page: int = 20,
) -> SubscriptionPaymentHistoryResponse:
    query = db.query(SubscriptionPayment).filter(SubscriptionPayment.id_clinica == tenant_id)
    total = query.count()
    offset = (page - 1) * per_page
    pagos = (
        query.order_by(SubscriptionPayment.fecha_creacion.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    items = [
        SubscriptionPaymentItem(
            id_pago=p.id_pago_suscripcion,
            monto=float(p.monto),
            moneda=p.moneda,
            ciclo=p.ciclo,
            estado=p.estado,
            numero_factura=p.numero_factura,
            fecha_pago=p.fecha_pago,
            fecha_creacion=p.fecha_creacion,
            plan_nombre=p.plan.nombre if p.plan else None,
        )
        for p in pagos
    ]

    return SubscriptionPaymentHistoryResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=items,
    )


def get_receipt_metadata(
    db: Session,
    tenant_id: int,
    id_pago: str,
) -> ReceiptMetadataResponse:
    pago = (
        db.query(SubscriptionPayment)
        .filter(SubscriptionPayment.id_pago_suscripcion == id_pago)
        .first()
    )
    if not pago or pago.id_clinica != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comprobante no encontrado para este tenant",
        )

    if pago.estado != "PAGADO":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El pago no ha sido confirmado; no se puede emitir comprobante",
        )

    clinica = db.query(Clinica).filter(Clinica.id_clinica == tenant_id).first()
    plan = db.query(PlanVersion).filter(PlanVersion.id_plan_version == pago.id_plan_version).first()

    return ReceiptMetadataResponse(
        id_pago=pago.id_pago_suscripcion,
        numero_factura=pago.numero_factura or "S/N",
        monto=float(pago.monto),
        moneda=pago.moneda,
        fecha_pago=pago.fecha_pago,
        tenant_nombre=clinica.nombre if clinica else "Tenant",
        plan_nombre=plan.nombre if plan else "Plan",
        ciclo=pago.ciclo,
        stripe_referencia=pago.stripe_session_id,
    )


def build_subscription_receipt_pdf(
    db: Session,
    tenant_id: int,
    id_pago: str,
) -> bytes:
    meta = get_receipt_metadata(db, tenant_id, id_pago)

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setTitle(f"Factura-{meta.numero_factura}")

    # Cabecera
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, "PLATAFORMA DE TELEMEDICINA - SAAS")
    c.setFont("Helvetica", 10)
    c.drawString(50, 735, "Comprobante de Suscripción de Plataforma")
    c.line(50, 725, 550, 725)

    # Datos del pago y factura
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, 690, f"Factura Nº: {meta.numero_factura}")
    c.setFont("Helvetica", 10)
    fecha_str = meta.fecha_pago.strftime("%d/%m/%Y %H:%M UTC") if meta.fecha_pago else "-"
    c.drawString(50, 670, f"Fecha de Pago: {fecha_str}")
    c.drawString(50, 650, f"Tenant / Entidad: {meta.tenant_nombre}")
    c.drawString(50, 630, f"Plan Contratado: {meta.plan_nombre}")
    c.drawString(50, 610, f"Ciclo de Facturación: {meta.ciclo}")
    c.drawString(50, 590, f"Monto Total: {meta.monto:.2f} {meta.moneda}")
    c.drawString(50, 570, f"Referencia Stripe: {meta.stripe_referencia or 'N/D'}")
    c.drawString(50, 550, f"Estado: CONFIRMADO / PAGADO")

    c.line(50, 525, 550, 525)
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, 505, "Documento digital válido emitido automáticamente.")
    c.drawString(50, 490, "Agradecemos su confianza en nuestra plataforma.")

    c.showPage()
    c.save()

    buffer.seek(0)
    return buffer.getvalue()

