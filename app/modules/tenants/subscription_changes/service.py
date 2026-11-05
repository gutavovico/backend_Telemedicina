from datetime import timedelta
from decimal import Decimal
from fastapi import HTTPException
from jose import jwt, JWTError
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.audit import registrar_auditoria
from app.modules.auth.models import Plan, VersionPlan
from app.modules.appointments.models import Medico
from app.modules.medical_records.hce.models import Consulta
from app.modules.tenants.models import SubscriptionChange, SubscriptionPayment
from app.modules.tenants.catalog import available_version
from app.modules.tenants.billing import utc, adjustment, next_month
from app.modules.tenants.subscription_payments import service as payments
from .schemas import QuoteResponse, ChangeResponse

PENDING = ('WAITING_PAYMENT', 'SCHEDULED', 'WAITING_RENEWAL')


def fail(detail, code='SUBSCRIPTION_CONFLICT'):
    raise HTTPException(409, {'code': code, 'message': detail})


def current(db, tenant_id):
    sub = payments.lock_subscription(db, tenant_id)
    if sub is None:
        raise HTTPException(404, 'La entidad no tiene suscripción')
    return sub


def ensure_no_pending(db, sub):
    if db.scalar(select(SubscriptionChange.id).where(
            SubscriptionChange.id_suscripcion == sub.id_suscripcion,
            SubscriptionChange.id_clinica == sub.id_clinica, SubscriptionChange.status.in_(PENDING))):
        fail('Ya existe una solicitud pendiente')


def require_paid_cycle(sub, now):
    if sub.estado != 'ACTIVE' or not utc(sub.fecha_inicio) <= now < utc(sub.fecha_fin):
        fail('Se requiere un ciclo pagado vigente')


def validate_limits(db, sub, target, cycle_start=None, cycle_end=None):
    # Read-only counts; no CU36 billing or invented zero consumption.
    doctors = db.scalar(select(func.count()).select_from(Medico).where(
        Medico.id_clinica == sub.id_clinica, func.lower(Medico.estado).in_(('activo','active'))))
    consultations = db.scalar(select(func.count()).select_from(Consulta).where(
        Consulta.id_clinica == sub.id_clinica, Consulta.fecha_consulta >= (cycle_start or sub.fecha_inicio),
        Consulta.fecha_consulta < (cycle_end or sub.fecha_fin)))
    for limit, used in [(target.limite_medicos, doctors), (target.limite_consultas, consultations)]:
        if limit is not None and used > limit:
            fail('El uso registrado supera los límites del destino', 'LIMIT_EXCEEDED')
    # No operational Sede model exists. Do not claim a reduction is safe.
    old = sub.plan_canonico.limite_sedes
    if target.limite_sedes is not None and (old is None or target.limite_sedes < old):
        fail('No hay medición de sedes para validar esta reducción', 'SEDE_USAGE_UNAVAILABLE')


def is_upgrade(source, target):
    nondecreasing = all(new is None or (old is not None and new >= old) for old, new in [
        (source.limite_medicos, target.limite_medicos), (source.limite_sedes, target.limite_sedes),
        (source.limite_consultas, target.limite_consultas)])
    return (target.precio_mensual >= source.precio_mensual and nondecreasing
            and set(source.servicios_incluidos) <= set(target.servicios_incluidos)
            and (target.precio_mensual > source.precio_mensual
                 or any(a != b for a, b in [(source.limite_medicos,target.limite_medicos),
                    (source.limite_sedes,target.limite_sedes),(source.limite_consultas,target.limite_consultas)])
                 or set(source.servicios_incluidos) != set(target.servicios_incluidos)))


def quote(db, tenant_id, version_id):
    sub = current(db, tenant_id); now = payments.now_utc()
    require_paid_cycle(sub, now)
    target = available_version(db, version_id)
    if not is_upgrade(sub.plan_canonico, target):
        fail('El cambio inmediato requiere un plan superior sin reducir prestaciones')
    validate_limits(db, sub, target)
    amount = adjustment(sub.plan_canonico.precio_mensual, target.precio_mensual, sub.fecha_inicio, sub.fecha_fin, now)
    expires = min(now + timedelta(minutes=5), utc(sub.fecha_fin))
    token = jwt.encode({'purpose':'cu35-quote', 'tenant':tenant_id, 'sub':sub.id_suscripcion,
        'source':sub.id_version_plan, 'target':target.id, 'row':sub.row_version,
        'amount':format(amount,'.2f'), 'effective':now.isoformat(), 'exp':int(expires.timestamp())},
        settings.JWT_SECRET_KEY, algorithm='HS256')
    return QuoteResponse(amount=amount, effective_at=now, cycle_end=sub.fecha_fin,
                         quote_token=token, expires_at=expires)


def _verify_quote(token, sub, target, now):
    try:
        data = jwt.decode(token or '', settings.JWT_SECRET_KEY, algorithms=['HS256'],
                          options={'verify_exp': False, 'verify_sub': False})
    except JWTError:
        fail('Cotización inválida o ausente')
    if (data.get('purpose') != 'cu35-quote' or data.get('tenant') != sub.id_clinica
            or data.get('sub') != sub.id_suscripcion or data.get('source') != sub.id_version_plan
            or data.get('target') != target.id or data.get('row') != sub.row_version
            or data.get('exp',0) <= now.timestamp()):
        fail('La cotización venció o cambió el contrato; vuelva a cotizar')
    return Decimal(data['amount'])


def response(db, change):
    result = ChangeResponse.model_validate(change)
    if change.target_version_id:
        from app.modules.auth.planes.schemas import VersionResponse
        result.target_version = VersionResponse.model_validate(db.get(VersionPlan,change.target_version_id))
    if change.payment_id:
        payment = db.scalar(select(SubscriptionPayment).where(
            SubscriptionPayment.id_pago_suscripcion == change.payment_id,
            SubscriptionPayment.id_clinica == change.id_clinica))
        if payment and payment.estado == 'PENDING':
            result.checkout_url = payment.url_checkout
    return result


def list_changes(db, tenant_id):
    return [response(db, c) for c in db.scalars(select(SubscriptionChange).where(
        SubscriptionChange.id_clinica == tenant_id).order_by(SubscriptionChange.requested_at.desc()).limit(100))]


def _audit(db, change, action):
    registrar_auditoria(db, id_usuario=change.requested_by, id_clinica=change.id_clinica,
        tabla_afectada='subscription_changes', accion=action,
        datos_nuevos={'change_id':change.id, 'status':change.status,
                      'source_version_id':change.source_version_id, 'target_version_id':change.target_version_id,
                      'effective_at':utc(change.effective_at).isoformat()})


def request_change(db, tenant_id, user, key, operation, target_id=None, quote_token=None):
    sub = current(db, tenant_id)
    previous = db.scalar(select(SubscriptionChange).where(
        SubscriptionChange.id_clinica == tenant_id, SubscriptionChange.idempotency_key == key))
    if previous:
        if previous.operation != operation or previous.target_version_id != target_id:
            fail('La clave de idempotencia ya identifica otra operación')
        return response(db, previous)
    now = payments.now_utc(); require_paid_cycle(sub, now); ensure_no_pending(db, sub)
    if db.scalar(select(SubscriptionPayment.id_pago_suscripcion).where(
            SubscriptionPayment.id_clinica == tenant_id, SubscriptionPayment.purpose == 'RENEWAL',
            SubscriptionPayment.estado.in_(('PENDING','PAGADO')),
            SubscriptionPayment.period_start >= sub.fecha_fin)):
        fail('Hay una renovación pendiente o prepagada; requiere conciliación antes de cambiar/cancelar')
    target = available_version(db, target_id, lock=True) if target_id else None
    if target:
        if target.id == sub.id_version_plan:
            fail('La versión elegida ya está contratada')
        validate_limits(db, sub, target,
            cycle_start=sub.fecha_fin if operation == 'NEXT_CYCLE' else None,
            cycle_end=next_month(sub.fecha_fin,sub.billing_anchor_day) if operation == 'NEXT_CYCLE' else None)
    amount = Decimal('0.00')
    if operation == 'IMMEDIATE':
        if not is_upgrade(sub.plan_canonico, target): fail('El destino no es un plan superior')
        amount = _verify_quote(quote_token, sub, target, now)
    change = SubscriptionChange(id_clinica=tenant_id, id_suscripcion=sub.id_suscripcion,
        requested_by=user.id_usuario, source_version_id=sub.id_version_plan, target_version_id=target_id,
        source_row_version=sub.row_version,
        operation=operation, status='WAITING_PAYMENT' if operation=='IMMEDIATE' else 'SCHEDULED',
        amount=amount, effective_at=now if operation=='IMMEDIATE' else sub.fecha_fin, idempotency_key=key)
    db.add(change)
    try:
        db.flush()
        if operation == 'IMMEDIATE':
            if amount > 0:
                payment = payments.prepare_payment(db, sub, user, target, amount, purpose='UPGRADE',
                                                  start=sub.fecha_inicio, end=sub.fecha_fin)
                change.payment_id = payment.id_pago_suscripcion
            else:
                _apply(db, sub, change, now)
        _audit(db, change, 'SOLICITAR_CAMBIO_SUSCRIPCION')
        db.commit()
    except IntegrityError:
        db.rollback(); fail('Otra solicitud concurrente ya fue registrada')
    db.refresh(change)
    return response(db, change)


def _apply(db, sub, change, now, renewal_payment=None):
    if (change.source_version_id != sub.id_version_plan or sub.estado == 'CANCELLED'
            or change.source_row_version != sub.row_version):
        fail('El contrato de origen cambió')
    if change.operation == 'CANCEL':
        sub.estado = 'CANCELLED'
    else:
        target = db.get(VersionPlan, change.target_version_id)
        plan = db.scalar(select(Plan).where(Plan.id == target.plan_id).with_for_update())
        if not plan.activo: fail('El destino fue desactivado')
        if change.operation == 'NEXT_CYCLE':
            if (renewal_payment is None or renewal_payment.estado != 'PAGADO'
                    or renewal_payment.id_version_plan != change.target_version_id
                    or renewal_payment.id_pago_suscripcion != change.payment_id
                    or utc(renewal_payment.period_start) != utc(change.effective_at)
                    or not utc(renewal_payment.period_start) <= now < utc(renewal_payment.period_end)):
                fail('El cambio programado requiere el pago confirmado de su ciclo')
            validate_limits(db, sub, target, cycle_start=renewal_payment.period_start,cycle_end=renewal_payment.period_end)
        else:
            validate_limits(db, sub, target)
        sub.id_version_plan = target.id; sub.plan_canonico = target; sub.dias_gracia = target.demora_pago_dias
        if change.operation == 'NEXT_CYCLE':
            sub.fecha_inicio = renewal_payment.period_start
            sub.fecha_fin = renewal_payment.period_end
            sub.estado = 'ACTIVE'
    sub.row_version += 1
    change.status = 'APPLIED'; change.applied_at = now
    if change.operation == 'IMMEDIATE': change.effective_at = now
    _audit(db, change, 'APLICAR_CAMBIO_SUSCRIPCION')


def apply_paid_upgrade(db, sub, payment):
    change = db.scalar(select(SubscriptionChange).where(
        SubscriptionChange.payment_id == payment.id_pago_suscripcion,
        SubscriptionChange.id_clinica == sub.id_clinica).with_for_update())
    if change is None: fail('Pago de ajuste sin solicitud asociada')
    if change.status == 'APPLIED': return
    if change.status != 'WAITING_PAYMENT':
        change.status = 'REVIEW_REQUIRED'; change.reason = 'Pago recibido para una solicitud cerrada'; return
    now = payments.now_utc()
    try:
        require_paid_cycle(sub, now)
        _apply(db, sub, change, now)
    except HTTPException as exc:
        change.status = 'REVIEW_REQUIRED'; change.reason = str(exc.detail)[:250]
        _audit(db, change, 'REVISAR_PAGO_CAMBIO')


def fail_payment_change(db, sub, payment):
    change = db.scalar(select(SubscriptionChange).where(
        SubscriptionChange.payment_id == payment.id_pago_suscripcion,
        SubscriptionChange.id_clinica == sub.id_clinica).with_for_update())
    if change and change.status in PENDING:
        change.status = 'WAITING_RENEWAL' if change.operation == 'NEXT_CYCLE' else 'FAILED'
        change.reason = payment.estado
        _audit(db, change, 'FALLAR_PAGO_CAMBIO')


def process_cycle(db, tenant_id, now=None):
    """Execute due actions; a new paid cycle always requires explicit CU31 acceptance."""
    now = utc(now or payments.now_utc()); sub = current(db, tenant_id)
    changes = db.scalars(select(SubscriptionChange).where(
        SubscriptionChange.id_clinica == tenant_id, SubscriptionChange.id_suscripcion == sub.id_suscripcion,
        SubscriptionChange.status.in_(('SCHEDULED','WAITING_RENEWAL')), SubscriptionChange.effective_at <= now)
        .with_for_update()).all()
    processed = 0
    for change in changes:
        if change.operation == 'NEXT_CYCLE':
            payment = db.get(SubscriptionPayment,change.payment_id) if change.payment_id else None
            if not payment or payment.estado != 'PAGADO':
                change.status='WAITING_RENEWAL'; change.reason='Esperando pago de la version de destino aceptada'
                continue
            payments.apply_paid_renewal(db,sub,payment,now)
            processed += 1
            continue
        try:
            _apply(db, sub, change, now)
        except HTTPException as exc:
            change.status='BLOCKED'; change.reason=str(exc.detail)[:250]
            _audit(db, change, 'BLOQUEAR_CAMBIO_SUSCRIPCION')
        processed += 1
    if not changes and sub.estado != 'CANCELLED' and utc(sub.fecha_fin) <= now:
        renewal = db.scalar(select(SubscriptionPayment).where(
            SubscriptionPayment.id_clinica == tenant_id, SubscriptionPayment.purpose == 'RENEWAL',
            SubscriptionPayment.estado == 'PAGADO', SubscriptionPayment.application_status == 'SCHEDULED',
            SubscriptionPayment.period_start == sub.fecha_fin,
            SubscriptionPayment.period_start <= now).with_for_update())
        if renewal:
            payments.apply_paid_renewal(db,sub,renewal,now)
            processed += 1
    db.commit()
    return processed
