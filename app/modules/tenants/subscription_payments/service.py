import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session
from app.core.config import settings
from app.modules.auth.models import Clinica, Usuario, Plan, VersionPlan
from app.modules.auth.planes.schemas import VersionResponse
from app.modules.payments.service import _stripe_request, stripe_habilitado, verificar_firma_stripe
from app.modules.tenants.models import SubscriptionPayment, TenantSubscription, SubscriptionChange
from app.modules.tenants.catalog import available_version, available_versions
from app.modules.tenants.billing import utc, next_month
from .schemas import (CheckoutResponse, CurrentSubscriptionResponse, PlanVersionItem,
    ReceiptMetadataResponse, SubscriptionPaymentHistoryResponse, SubscriptionPaymentItem)


def now_utc():
    return datetime.now(timezone.utc)


def _webhook_secret():
    secret = settings.STRIPE_WEBHOOK_SECRET
    return secret.get_secret_value().strip() if hasattr(secret, 'get_secret_value') else str(secret or '').strip()


def _url_con_pago(url, payment_id):
    return f"{url}{'&' if '?' in url else '?'}pago={payment_id}"


def lock_subscription(db, tenant_id):
    return db.scalar(select(TenantSubscription).where(TenantSubscription.id_clinica == tenant_id)
        .with_for_update().execution_options(populate_existing=True))


def _crear_sesion_stripe(plan, pago, monto, ciclo):
    return _stripe_request('POST', '/v1/checkout/sessions', data={
        'mode':'payment', 'line_items[0][quantity]':1,
        'line_items[0][price_data][currency]':'bob',
        'line_items[0][price_data][unit_amount]':int(monto * 100),
        'line_items[0][price_data][product_data][name]':f'Suscripción {plan.nombre} ({ciclo})',
        'success_url':_url_con_pago(settings.SUBSCRIPTION_WEB_SUCCESS_URL, pago.id_pago_suscripcion),
        'cancel_url':settings.SUBSCRIPTION_WEB_CANCEL_URL,
        'client_reference_id':f'suscripcion-{pago.id_pago_suscripcion}',
        'metadata[id_pago_suscripcion]':pago.id_pago_suscripcion,
        'metadata[tenant_id]':pago.id_clinica, 'metadata[tipo]':'suscripcion',
    })


def prepare_payment(db, sub, user, version, amount, purpose='RENEWAL', start=None, end=None):
    payment = SubscriptionPayment(id_suscripcion=sub.id_suscripcion, id_clinica=sub.id_clinica,
        tenant_id=sub.tenant_id, id_usuario=user.id_usuario, id_version_plan=version.id,
        ciclo='MONTHLY', monto=amount, moneda='BOB', estado='PENDING', purpose=purpose,
        period_start=start, period_end=end, source_row_version=sub.row_version, expira_en=now_utc()+timedelta(hours=2))
    db.add(payment); db.flush()
    if amount > 0 and stripe_habilitado():
        session = _crear_sesion_stripe(version, payment, amount, 'MENSUAL')
        if not session.get('id') or not session.get('url'):
            db.rollback()
            raise HTTPException(502, 'Stripe no devolvió un checkout válido')
        payment.stripe_session_id, payment.url_checkout = session['id'], session['url']
    else:
        payment.stripe_session_id = 'cs_sub_'+uuid.uuid4().hex
        payment.url_checkout = _url_con_pago(settings.SUBSCRIPTION_WEB_SUCCESS_URL.split('?')[0]
            +'?checkout=simulated', payment.id_pago_suscripcion)
    return payment


def checkout_response(payment):
    return CheckoutResponse(id_pago=payment.id_pago_suscripcion, monto=payment.monto,
        moneda=payment.moneda, checkout_url=payment.url_checkout, expira_en=payment.expira_en)


def get_current_subscription(db, tenant_id):
    sub = db.scalar(select(TenantSubscription).where(TenantSubscription.id_clinica == tenant_id))
    if sub is None:
        return CurrentSubscriptionResponse(has_subscription=False)
    now = now_utc(); end = utc(sub.fecha_fin)
    derived = sub.estado
    if sub.estado not in ('CANCELLED', 'TRIALING'):
        derived = ('EXPIRED' if now >= end+timedelta(days=sub.dias_gracia)
                   else 'DUE_SOON' if now >= end-timedelta(days=5) else sub.estado)
    plan = sub.plan_canonico
    return CurrentSubscriptionResponse(id_plan_version=plan.id, has_subscription=True, id_suscripcion=sub.id_suscripcion,
        tenant_id=sub.tenant_id or str(sub.id_clinica), plan_nombre=plan.nombre,
        plan_version_id=plan.id, version=VersionResponse.model_validate(plan), row_version=sub.row_version,
        ciclo='MONTHLY', fecha_inicio=sub.fecha_inicio, fecha_fin=sub.fecha_fin,
        dias_gracia=sub.dias_gracia, estado=sub.estado, derived_status=derived,
        limite_medicos=plan.limite_medicos, limite_sedes=plan.limite_sedes,
        limite_consultas_mes=plan.limite_consultas)


def list_active_plans(db):
    return [PlanVersionItem(**VersionResponse.model_validate(v).model_dump(),
        id_plan_version=v.id, limite_consultas_mes=v.limite_consultas) for v in available_versions(db)]


def create_subscription_checkout(db, tenant_id, user, plan_version_id, cycle):
    if cycle not in ('MENSUAL','MONTHLY'):
        raise HTTPException(422, 'Solo se admite MENSUAL')
    # Serialize first contracts as well as renewals on the tenant row.
    clinic = db.scalar(select(Clinica).where(Clinica.id_clinica == tenant_id).with_for_update())
    if clinic is None:
        raise HTTPException(404, 'Entidad no encontrada')
    sub = lock_subscription(db, tenant_id)
    if sub and sub.estado == 'CANCELLED':
        raise HTTPException(409, 'La suscripción está cancelada')
    from app.modules.tenants.subscription_changes.service import PENDING, validate_limits
    scheduled = None
    if sub:
        scheduled = db.scalar(select(SubscriptionChange).where(
            SubscriptionChange.id_clinica == tenant_id, SubscriptionChange.id_suscripcion == sub.id_suscripcion,
            SubscriptionChange.status.in_(PENDING)).with_for_update())
    if scheduled and scheduled.operation != 'NEXT_CYCLE':
        raise HTTPException(409, 'La solicitud pendiente impide renovar, incluida una cancelación programada')
    if scheduled:
        if scheduled.target_version_id != plan_version_id:
            raise HTTPException(409, 'Debe aceptar la versión exacta del cambio programado')
        version = db.get(VersionPlan, scheduled.target_version_id)
        if not db.get(Plan,version.plan_id).activo:
            raise HTTPException(422, 'El plan de destino fue desactivado')
    else:
        version = available_version(db, plan_version_id)
        if sub and sub.estado != 'TRIALING' and version.plan_id != sub.plan_canonico.plan_id:
            raise HTTPException(409, 'El cambio a otro plan requiere CU35')
    now = now_utc()
    if not sub:
        sub = TenantSubscription(id_clinica=tenant_id, tenant_id=clinic.tenant_id,
            id_version_plan=version.id, ciclo='MONTHLY', fecha_inicio=now, fecha_fin=now,
            dias_gracia=version.demora_pago_dias, billing_anchor_day=now.day, estado='TRIALING', row_version=1)
        db.add(sub); db.flush()
    if sub.billing_anchor_day is None:
        if sub.estado != 'TRIALING':
            raise HTTPException(409, 'La suscripción requiere conciliar su ancla mensual original')
        sub.billing_anchor_day = now.day
    pending = db.scalar(select(SubscriptionPayment).where(
        SubscriptionPayment.id_clinica==tenant_id, SubscriptionPayment.estado=='PENDING',
        SubscriptionPayment.purpose=='RENEWAL', SubscriptionPayment.expira_en>now).order_by(
            SubscriptionPayment.fecha_creacion.desc()))
    if pending:
        if pending.id_version_plan != version.id:
            raise HTTPException(409, 'Hay otro checkout pendiente con una versión distinta')
        return checkout_response(pending)
    start = (utc(scheduled.effective_at) if scheduled else
             utc(sub.fecha_fin) if sub.estado == 'ACTIVE' and utc(sub.fecha_fin)>now else now)
    end = next_month(start, sub.billing_anchor_day)
    if end <= now:
        raise HTTPException(409, 'El ciclo programado terminó sin renovarse; requiere conciliación')
    if sub.estado != 'TRIALING':
        validate_limits(db, sub, version, cycle_start=start, cycle_end=end)
    if db.scalar(select(SubscriptionPayment.id_pago_suscripcion).where(
            SubscriptionPayment.id_clinica == tenant_id, SubscriptionPayment.purpose == 'RENEWAL',
            SubscriptionPayment.estado == 'PAGADO', SubscriptionPayment.period_start == start,
            SubscriptionPayment.period_end == end)):
        raise HTTPException(409, 'Ese ciclo ya está pagado; no se generará otro cobro')
    amount = Decimal(version.precio_mensual).quantize(Decimal('0.01'))
    payment = prepare_payment(db, sub, user, version, amount, start=start, end=end)
    if scheduled:
        scheduled.payment_id = payment.id_pago_suscripcion
        scheduled.status = 'SCHEDULED'
        scheduled.reason = None
    db.commit(); db.refresh(payment)
    if amount == 0:
        # No gateway charge exists for a free renewal; still preserve a paid ledger entry.
        confirm_subscription_payment(db, payment.id_pago_suscripcion)
    return checkout_response(payment)


def confirm_subscription_payment(db, stripe_session_id_or_payment_id):
    ref = db.scalar(select(SubscriptionPayment).where(or_(
        SubscriptionPayment.stripe_session_id==stripe_session_id_or_payment_id,
        SubscriptionPayment.id_pago_suscripcion==stripe_session_id_or_payment_id)))
    if ref is None:
        raise HTTPException(404, 'Pago no encontrado')
    sub = lock_subscription(db, ref.id_clinica)
    payment = db.scalar(select(SubscriptionPayment).where(
        SubscriptionPayment.id_pago_suscripcion==ref.id_pago_suscripcion,
        SubscriptionPayment.id_clinica==sub.id_clinica).with_for_update().execution_options(populate_existing=True))
    if payment.estado == 'PAGADO':
        return payment
    payment.estado = 'PAGADO'; payment.fecha_pago = now_utc()
    payment.numero_factura = payment.numero_factura or 'FAC-SUB-'+uuid.uuid4().hex[:12].upper()
    if payment.purpose == 'UPGRADE':
        from app.modules.tenants.subscription_changes.service import apply_paid_upgrade
        apply_paid_upgrade(db, sub, payment)
        change = db.scalar(select(SubscriptionChange).where(SubscriptionChange.payment_id == payment.id_pago_suscripcion))
        payment.application_status = 'APPLIED' if change.status == 'APPLIED' else 'REVIEW_REQUIRED'
        payment.application_reason = change.reason
    elif payment.period_start and now_utc() < utc(payment.period_start):
        pending = db.scalar(select(SubscriptionChange).where(
            SubscriptionChange.id_suscripcion == sub.id_suscripcion, SubscriptionChange.id_clinica == sub.id_clinica,
            SubscriptionChange.status.in_(('WAITING_PAYMENT','SCHEDULED','WAITING_RENEWAL'))))
        incompatible = (sub.estado == 'CANCELLED'
            or (payment.source_row_version is not None and payment.source_row_version != sub.row_version)
            or (pending is not None and pending.payment_id != payment.id_pago_suscripcion))
        payment.application_status = 'REVIEW_REQUIRED' if incompatible else 'SCHEDULED'
        if incompatible:
            payment.application_reason = 'Contrato o solicitud pendiente incompatible con el pago recibido'

    else:
        apply_paid_renewal(db, sub, payment, now_utc())
    db.commit(); db.refresh(payment)
    return payment


def apply_paid_renewal(db, sub, payment, now):
    if payment.application_status == 'APPLIED':
        return payment
    from app.modules.tenants.subscription_changes import service as changes
    pending = db.scalar(select(SubscriptionChange).where(SubscriptionChange.payment_id == payment.id_pago_suscripcion,
        SubscriptionChange.id_clinica == sub.id_clinica).with_for_update())
    try:
        if payment.estado != 'PAGADO' or payment.purpose != 'RENEWAL':
            raise HTTPException(409, 'No hay pago de renovación confirmado')
        if not payment.period_start or not utc(payment.period_start) <= now < utc(payment.period_end):
            raise HTTPException(409, 'El pago no corresponde a un ciclo aplicable')
        if sub.estado == 'CANCELLED' or (payment.source_row_version is not None and payment.source_row_version != sub.row_version):
            raise HTTPException(409, 'El contrato cambió desde la aceptación de la renovación')
        active_request = db.scalar(select(SubscriptionChange).where(
            SubscriptionChange.id_suscripcion == sub.id_suscripcion,
            SubscriptionChange.id_clinica == sub.id_clinica, SubscriptionChange.status.in_(changes.PENDING)))
        if active_request and (pending is None or active_request.id != pending.id):
            raise HTTPException(409, 'El pago no corresponde a la solicitud pendiente; requiere conciliacion')
        if pending:
            changes._apply(db, sub, pending, now, renewal_payment=payment)
        else:
            changes.validate_limits(db,sub,payment.plan_canonico,cycle_start=payment.period_start,cycle_end=payment.period_end)
            sub.id_version_plan=payment.id_version_plan; sub.plan_canonico=payment.plan_canonico
            sub.fecha_inicio=payment.period_start; sub.fecha_fin=payment.period_end
            sub.dias_gracia=payment.plan_canonico.demora_pago_dias; sub.estado='ACTIVE'; sub.row_version+=1
        payment.application_status='APPLIED'; payment.application_reason=None
    except HTTPException as exc:
        payment.application_status='REVIEW_REQUIRED'; payment.application_reason=str(exc.detail)[:250]
        if pending:
            pending.status='REVIEW_REQUIRED'; pending.reason=payment.application_reason
    return payment


def verified_payment(db, payment, session):
    if (session.get('payment_status') != 'paid'
            or session.get('amount_total') != int(Decimal(payment.monto)*100)
            or str(session.get('currency','')).upper() != 'BOB'
            or session.get('id') != payment.stripe_session_id):
        raise HTTPException(422, 'Confirmación de pasarela no coincide con el pago')
    return confirm_subscription_payment(db, payment.id_pago_suscripcion)


def sincronizar_checkout_suscripcion(db, tenant_id, id_pago):
    payment = db.scalar(select(SubscriptionPayment).where(
        SubscriptionPayment.id_pago_suscripcion==id_pago, SubscriptionPayment.id_clinica==tenant_id))
    if payment is None:
        raise HTTPException(404, 'Pago no encontrado para esta entidad')
    if payment.estado=='PAGADO' or not stripe_habilitado():
        return payment
    session = _stripe_request('GET','/v1/checkout/sessions/'+payment.stripe_session_id)
    return verified_payment(db,payment,session) if session.get('payment_status')=='paid' else payment


def procesar_webhook_suscripcion(db, payload, signature_header):
    verificar_firma_stripe(payload, signature_header, _webhook_secret())
    try:
        event=json.loads(payload)
    except (ValueError, UnicodeError):
        raise HTTPException(400,'Webhook inválido')
    session=(event.get('data') or {}).get('object') or {}
    payment=db.scalar(select(SubscriptionPayment).where(SubscriptionPayment.stripe_session_id==session.get('id')))
    if payment is None:
        return {'received':True,'ignored':True}
    kind=event.get('type')
    if kind in ('checkout.session.completed','checkout.session.async_payment_succeeded'):
        if session.get('payment_status')=='paid':
            payment=verified_payment(db,payment,session)
    elif kind in ('checkout.session.expired','checkout.session.async_payment_failed') and payment.estado=='PENDING':
        sub=lock_subscription(db,payment.id_clinica)
        payment=db.scalar(select(SubscriptionPayment).where(SubscriptionPayment.id_pago_suscripcion==payment.id_pago_suscripcion)
            .with_for_update().execution_options(populate_existing=True))
        if payment.estado=='PENDING':
            payment.estado='CANCELADO' if kind=='checkout.session.expired' else 'FALLIDO'
            payment.application_status='NOT_APPLIED'
            from app.modules.tenants.subscription_changes.service import fail_payment_change
            fail_payment_change(db,sub,payment)
            db.commit()
    return {'received':True,'id_pago':payment.id_pago_suscripcion,'estado':payment.estado}


def list_subscription_payments(db, tenant_id, page, per_page):
    where=SubscriptionPayment.id_clinica==tenant_id
    total=db.scalar(select(func.count()).select_from(SubscriptionPayment).where(where))
    rows=db.scalars(select(SubscriptionPayment).where(where).order_by(
        SubscriptionPayment.fecha_creacion.desc()).offset((page-1)*per_page).limit(per_page)).all()
    return SubscriptionPaymentHistoryResponse(total=total,page=page,per_page=per_page,items=[
        SubscriptionPaymentItem(application_status=p.application_status,application_reason=p.application_reason,plan_version_id=p.id_version_plan,version=VersionResponse.model_validate(p.plan_canonico),purpose=p.purpose,
            id_pago=p.id_pago_suscripcion,monto=p.monto,moneda=p.moneda,ciclo=p.ciclo,
            estado=p.estado,plan_nombre=p.plan_canonico.nombre,numero_factura=p.numero_factura,
            fecha_pago=p.fecha_pago,fecha_creacion=p.fecha_creacion) for p in rows])


def get_receipt_metadata(db, tenant_id, id_pago):
    payment=db.scalar(select(SubscriptionPayment).where(
        SubscriptionPayment.id_pago_suscripcion==id_pago,SubscriptionPayment.id_clinica==tenant_id))
    if payment is None: raise HTTPException(404,'Comprobante no encontrado para esta entidad')
    if payment.estado!='PAGADO': raise HTTPException(422,'El pago no ha sido confirmado')
    clinic=db.get(Clinica,tenant_id)
    return ReceiptMetadataResponse(plan_version_id=payment.id_version_plan,purpose=payment.purpose,
        id_pago=payment.id_pago_suscripcion,numero_factura=payment.numero_factura,
        monto=payment.monto,moneda=payment.moneda,fecha_pago=payment.fecha_pago,
        tenant_nombre=clinic.nombre,plan_nombre=payment.plan_canonico.nombre,ciclo='MONTHLY',
        stripe_referencia=payment.stripe_session_id)


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
    c.drawString(50, 630, f"Plan Contratado: {meta.plan_nombre} (version ID {meta.plan_version_id})")
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

