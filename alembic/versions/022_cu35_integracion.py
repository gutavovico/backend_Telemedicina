"""CU35 after the team's immutable 020/021; explicit historical reconciliation.

No name matching. Legacy rows require operator-reviewed per-row version maps.
"""
import json
from decimal import Decimal
from alembic import context, op
import sqlalchemy as sa

revision = 'cu35_integracion_022'
down_revision = 'cu06_servicios_clinica_021'
branch_labels = depends_on = None
AUDIT = ("id_clinica IS NOT NULL OR COALESCE(tabla_afectada IN ('planes','versiones_plan') OR "
         "(tabla_afectada='tenant_requests' AND accion='RECHAZAR_TENANT_REQUEST') OR "
         "(tabla_afectada='tenant_management' AND accion='ACCESO_DENEGADO'), FALSE)")


def upgrade():
    bind=op.get_bind()
    args=context.get_x_argument(as_dictionary=True)
    maps={name:json.loads(args.get(name,'{}')) for name in
          ('subscription_version_map','payment_version_map','plan_version_map','billing_anchor_map')}
    for name,mapping in maps.items():
        if not isinstance(mapping,dict) or any(type(k) is not str or type(v) is not int or v<1 for k,v in mapping.items()):
            raise RuntimeError('CU35: mapa explicito invalido '+name)
    updates=[]
    for table,pk,map_name in [('tenant_subscriptions','id_suscripcion','subscription_version_map'),
                              ('subscription_payments','id_pago_suscripcion','payment_version_map')]:
        rows=bind.execute(sa.text(f'SELECT * FROM {table}')).mappings().all()
        for row in rows:
            legacy=row['id_plan_version']
            target_id=maps[map_name].get(row[pk]) if legacy else row['id_version_plan']
            if not target_id:
                raise RuntimeError(f'CU35: {table}/{row[pk]} requiere {map_name} explicito; no confiar en mapeo por nombre de 020')
            target=bind.execute(sa.text('SELECT * FROM versiones_plan WHERE id=:id'),{'id':target_id}).mappings().first()
            if target is None:
                raise RuntimeError('CU35: version explicita inexistente')
            if legacy:
                old=bind.execute(sa.text('SELECT * FROM plan_versions WHERE id_plan_version=:id'),{'id':legacy}).mappings().one()
                amount=row['monto'] if table=='subscription_payments' else old['precio_mensual']
                if (Decimal(amount)!=target['precio_mensual'] or old['moneda']!=target['moneda']
                        or old['limite_medicos']!=target['limite_medicos']
                        or old['limite_consultas_mes']!=target['limite_consultas']):
                    raise RuntimeError('CU35: mapa no conserva condiciones historicas; preparar snapshot fiel, no inferir')
            if row['ciclo']!='MONTHLY':
                raise RuntimeError('CU35: ciclo antiguo no mensual requiere conciliacion')
            if table=='tenant_subscriptions' and row[pk] not in maps['billing_anchor_map']:
                raise RuntimeError('CU35: suscripcion existente requiere billing_anchor_map para conservar su ancla original')
            updates.append((table,pk,row[pk],target_id))
    for table,pk,legacy_col in [('tenant_requests','id_request','plan_version_id'),('clinicas','id_clinica','plan_id')]:
        for row in bind.execute(sa.text(f'SELECT * FROM {table} WHERE {legacy_col} IS NOT NULL')).mappings():
            target=maps['plan_version_map'].get(row[legacy_col])
            if not target or not bind.scalar(sa.text('SELECT count(*) FROM versiones_plan WHERE id=:id'),{'id':target}):
                raise RuntimeError('CU35: referencia legacy de '+table+' requiere plan_version_map explicito')
            updates.append((table,pk,row[pk],target))
    if any(day>31 for day in maps['billing_anchor_map'].values()):
        raise RuntimeError('CU35: ancla original debe estar entre 1 y 31')
    if bind.scalar(sa.text('SELECT count(*) FROM auditoria WHERE NOT ('+AUDIT+')')):
        raise RuntimeError('CU35: auditorias globales ajenas requieren revision; no se borran')
    # All checks precede mutation. Legacy mapping table remains historical evidence.
    for table,pk,row_id,target in updates:
        bind.execute(sa.text(f'UPDATE {table} SET id_version_plan=:target WHERE {pk}=:id'),{'target':target,'id':row_id})
    for table in ('tenant_subscriptions','subscription_payments'):
        op.alter_column(table,'id_version_plan',nullable=False)
    op.add_column('tenant_subscriptions',sa.Column('billing_anchor_day',sa.Integer()))
    for key,day in maps['billing_anchor_map'].items():
        bind.execute(sa.text('UPDATE tenant_subscriptions SET billing_anchor_day=:day WHERE id_suscripcion=:id'),{'day':day,'id':key})
    op.alter_column('subscription_payments','monto',existing_type=sa.Numeric(10,2),type_=sa.Numeric(14,2))
    for column in [sa.Column('purpose',sa.String(20),nullable=False,server_default='RENEWAL'),
                   sa.Column('source_row_version',sa.Integer()),
                   sa.Column('application_status',sa.String(24),nullable=False,server_default='PENDING'),
                   sa.Column('application_reason',sa.String(250)),
                   sa.Column('period_start',sa.DateTime(timezone=True)),sa.Column('period_end',sa.DateTime(timezone=True))]:
        op.add_column('subscription_payments',column)
    bind.execute(sa.text("UPDATE subscription_payments SET application_status='APPLIED' WHERE estado='PAGADO'"))
    op.create_table('subscription_changes',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('id_clinica',sa.BigInteger(),sa.ForeignKey('clinicas.id_clinica'),nullable=False),
        sa.Column('id_suscripcion',sa.String(36),sa.ForeignKey('tenant_subscriptions.id_suscripcion'),nullable=False),
        sa.Column('requested_by',sa.BigInteger(),sa.ForeignKey('usuarios.id_usuario'),nullable=False),
        sa.Column('source_version_id',sa.BigInteger(),sa.ForeignKey('versiones_plan.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('source_row_version',sa.Integer(),nullable=False),
        sa.Column('target_version_id',sa.BigInteger(),sa.ForeignKey('versiones_plan.id',ondelete='RESTRICT')),
        sa.Column('operation',sa.String(20),nullable=False),sa.Column('status',sa.String(24),nullable=False),
        sa.Column('amount',sa.Numeric(14,2),nullable=False),sa.Column('effective_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('requested_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('applied_at',sa.DateTime(timezone=True)),sa.Column('payment_id',sa.String(36),sa.ForeignKey('subscription_payments.id_pago_suscripcion'),unique=True),
        sa.Column('idempotency_key',sa.String(64),nullable=False),sa.Column('reason',sa.String(250)),
        sa.UniqueConstraint('id_clinica','idempotency_key',name='uq_change_tenant_key'),
        sa.CheckConstraint("operation IN ('IMMEDIATE','NEXT_CYCLE','CANCEL')",name='ck_change_operation'),
        sa.CheckConstraint('amount>=0',name='ck_change_amount'))
    op.create_index('ix_subscription_changes_id_clinica','subscription_changes',['id_clinica'])
    op.create_index('uq_subscription_pending_change','subscription_changes',['id_suscripcion'],unique=True,
        postgresql_where=sa.text("status IN ('WAITING_PAYMENT','SCHEDULED','WAITING_RENEWAL')"))
    op.create_check_constraint('ck_auditoria_global_catalogo','auditoria',AUDIT)


def downgrade():
    raise RuntimeError('CU35: preservar historial requiere downgrade explicito')
