"""CU35 entitlement gate; no CU36 consumption checks and no tenant deletion."""
from fastapi import HTTPException
from sqlalchemy import inspect, select
from app.modules.tenants.models import TenantSubscription, SubscriptionChange
from app.modules.tenants.billing import utc
from app.modules.tenants.subscription_payments import service as payments

CLINICAL_MODULES = ('app.modules.medical_records.', 'app.modules.appointments.',
                    'app.modules.analytics.', 'app.modules.communications.')

# Estas rutas son de contexto personal / autogestión: un médico con vínculo
# INVITADO o SUSPENDIDO debe poder cargarlas para aceptar/rechazar invitaciones
# y consultar su bandeja. El gate de suscripción no debe bloquearlas.
SELF_SERVICE_MODULES = (
    'app.modules.appointments.doctor_entity_links.router',
    'app.modules.appointments.doctor_profile.router',
    'app.modules.communications.notificaciones.router',
)


def assert_clinical_access(db, tenant_id, now=None):
    if tenant_id is None:
        return
    # Esquemas heredados o fixtures ligeras pueden no tener aun las tablas de
    # suscripcion. En ese caso se conserva la politica previa: sin suscripcion
    # no hay bloqueo. Cuando las tablas existen, el gate actua con normalidad.
    inspector = inspect(db.get_bind())
    if (not inspector.has_table(TenantSubscription.__tablename__)
            or not inspector.has_table(SubscriptionChange.__tablename__)):
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
    endpoint_module = getattr(endpoint, '__module__', '')
    if endpoint_module.startswith(SELF_SERVICE_MODULES):
        return
    if not endpoint_module.startswith(CLINICAL_MODULES):
        return
    tenant_id = user.id_clinica
    if tenant_id is None:
        # Reuse existing tenant resolution, including the legacy patient mapping.
        from app.modules.auth.dependencies import get_required_tenant_id, _is_global_super_admin
        try:
            tenant_id = get_required_tenant_id(connection.headers.get('X-Tenant-ID'), user, db=db)
        except HTTPException:
            if _is_global_super_admin(user) and not connection.headers.get('X-Tenant-ID'):
                return  # Preserve existing global administration without inventing a tenant.
            raise
    assert_clinical_access(db, tenant_id)
