"""CU35 entitlement gate; no CU36 consumption checks and no tenant deletion."""
from fastapi import HTTPException
from sqlalchemy import select
from app.modules.tenants.models import TenantSubscription, SubscriptionChange
from app.modules.tenants.billing import utc
from app.modules.tenants.subscription_payments import service as payments

CLINICAL_MODULES = ('app.modules.medical_records.', 'app.modules.appointments.',
                    'app.modules.analytics.', 'app.modules.communications.')


def assert_clinical_access(db, tenant_id, now=None):
    if tenant_id is None:
        return
    now = utc(now or payments.now_utc())
    sub = db.scalar(select(TenantSubscription).where(TenantSubscription.id_clinica == tenant_id))
    if sub is None:
        return  # Existing entities without subscriptions retain their previous policy.
    pending_cancel = db.scalar(select(SubscriptionChange.id).where(
        SubscriptionChange.id_clinica == tenant_id, SubscriptionChange.id_suscripcion == sub.id_suscripcion,
        SubscriptionChange.operation == 'CANCEL', SubscriptionChange.status == 'SCHEDULED',
        SubscriptionChange.effective_at <= now))
    if (sub.estado == 'CANCELLED' and now >= utc(sub.fecha_fin)) or pending_cancel:
        raise HTTPException(403, 'La suscripción finalizó; el administrador conserva acceso a suscripción y facturación',
                            headers={'X-Subscription-Status':'CANCELLED'})


def check_authenticated_endpoint(db, user, connection):
    endpoint = connection.scope.get('endpoint')
    if not getattr(endpoint, '__module__', '').startswith(CLINICAL_MODULES):
        return
    tenant_id = user.id_clinica
    if tenant_id is None:
        # Reuse existing tenant resolution, including the legacy patient mapping.
        from app.modules.auth.dependencies import get_required_tenant_id, _is_global_super_admin
        try:
            tenant_id = get_required_tenant_id(connection.headers.get('X-Tenant-ID'), user)
        except HTTPException:
            if _is_global_super_admin(user) and not connection.headers.get('X-Tenant-ID'):
                return  # Preserve existing global administration without inventing a tenant.
            raise
    assert_clinical_access(db, tenant_id)
