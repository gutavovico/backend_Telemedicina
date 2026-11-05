import importlib.util
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch
import pytest
from fastapi import FastAPI, Depends, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import Base, get_db
from app.modules.auth.models import Clinica, Rol, Usuario, Plan, VersionPlan
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.planes import service as catalog
from app.modules.auth.planes.schemas import VersionCreate
from app.modules.tenants.models import TenantSubscription, SubscriptionPayment, SubscriptionChange
from app.modules.tenants.subscription_payments import service as payments
from app.modules.tenants.subscription_payments.router import router as pay_router
from app.modules.tenants.subscription_changes.router import router as change_router
from app.modules.tenants.subscription_changes import service as changes
from app.modules.tenants.billing import utc, next_month, adjustment

START=datetime(2026,1,31,tzinfo=timezone.utc)
END=datetime(2026,2,28,tzinfo=timezone.utc)
NOW=datetime(2026,2,14,tzinfo=timezone.utc)


@pytest.fixture
def env(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def fk(conn,_): conn.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False)
    db=sessions()
    for i in [1,2]:
        db.add(Clinica(id_clinica=i,nombre='Entidad '+str(i),estado='ACTIVE'))
    db.flush()
    for rid, clinic, name in [(1,1,'ADMIN'),(2,2,'ADMIN'),(90,None,'Super Administrador'),(3,1,'MEDICO')]:
        db.add(Rol(id_rol=rid,id_clinica=clinic,nombre=name,estado='ACTIVO'))
    db.flush()
    for uid,clinic,role in [(1,1,1),(2,2,2),(90,None,90),(3,1,3)]:
        db.add(Usuario(id_usuario=uid,id_clinica=clinic,id_rol=role,nombres='Prueba',apellidos='CU35',
            correo=f'cu35-{uid}@example.test',password_hash='not-a-login',estado='ACTIVO'))
    db.flush()
    for pid, price, doctors in [(1,'200.00',10),(2,'500.00',20),(3,'100.00',5)]:
        db.add(Plan(id=pid,codigo='TEST'+str(pid),activo=True,version_actual=1));db.flush()
        db.add(VersionPlan(id=pid,plan_id=pid,numero=1,nombre='Plan '+str(pid),precio_mensual=price,
            moneda='BOB',ciclo='MENSUAL',limite_medicos=doctors,limite_sedes=None,limite_consultas=None,
            servicios_incluidos=['AGENDA_TELECONSULTA'],tarifas_excedentes=[],demora_pago_dias=0,creado_por=90))
    db.flush()
    for tenant in [1,2]:
        db.add(TenantSubscription(id_suscripcion='sub-'+str(tenant),id_clinica=tenant,id_version_plan=1,
            ciclo='MENSUAL',fecha_inicio=START,fecha_fin=END,dias_gracia=0,billing_anchor_day=31,
            estado='ACTIVE',row_version=1))
    db.commit()
    monkeypatch.setattr(payments,'now_utc',lambda: NOW)
    monkeypatch.setattr(payments,'stripe_habilitado',lambda:False)
    app=FastAPI();app.include_router(pay_router,prefix='/api/v1');app.include_router(change_router)
    def session(): yield db
    def actor(x_test_actor:int=Header(1)): return db.get(Usuario,x_test_actor)
    app.dependency_overrides[get_db]=session;app.dependency_overrides[get_current_user]=actor
    client=TestClient(app)
    yield db,client,sessions
    client.close();db.close();engine.dispose()


def upgrade(client,key='upgrade-key-1'):
    q=client.post('/api/v1/subscriptions/quote',json={'plan_version_id':2})
    assert q.status_code==200,q.text
    assert q.json()['amount']=='150.00'
    r=client.post('/api/v1/subscriptions/changes',json={'plan_version_id':2,'mode':'IMMEDIATE',
        'idempotency_key':key,'quote_token':q.json()['quote_token']})
    assert r.status_code==201,r.text
    return r.json()


def test_paid_upgrade_keeps_cycle_and_duplicate_confirmation(env):
    db,client,_=env
    change=upgrade(client)
    sub=db.get(TenantSubscription,'sub-1')
    assert sub.id_version_plan==1
    payment=db.get(SubscriptionPayment,change['payment_id'])
    assert payment.id_version_plan==2 and payment.monto==Decimal('150.00')
    payments.confirm_subscription_payment(db,payment.id_pago_suscripcion)
    assert sub.id_version_plan==2 and utc(sub.fecha_inicio)==START and utc(sub.fecha_fin)==END
    assert db.get(SubscriptionChange,change['id']).status=='APPLIED'
    row=sub.row_version
    payments.confirm_subscription_payment(db,payment.id_pago_suscripcion)
    assert sub.row_version==row and utc(sub.fecha_fin)==END


def test_failed_gateway_keeps_original_contract(env):
    db,client,_=env
    change=upgrade(client)
    payment=db.get(SubscriptionPayment,change['payment_id'])
    event_data={'type':'checkout.session.async_payment_failed',
                'data':{'object':{'id':payment.stripe_session_id}}}
    import json
    with patch.object(payments,'verificar_firma_stripe'):
        payments.procesar_webhook_suscripcion(db,json.dumps(event_data).encode(),'test')
    assert db.get(TenantSubscription,'sub-1').id_version_plan==1
    assert db.get(SubscriptionChange,change['id']).status=='FAILED'


def test_existing_subscription_without_original_anchor_cannot_renew(env):
    db,client,_=env
    sub=db.get(TenantSubscription,'sub-1')
    sub.billing_anchor_day=None
    db.commit()
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='ancla mensual original') as exc:
        payments.create_subscription_checkout(db,1,db.get(Usuario,1),1,'MONTHLY')
    assert exc.value.status_code==409
    assert sub.billing_anchor_day is None
    assert db.scalar(select(SubscriptionPayment)) is None


def test_late_paid_upgrade_requires_review_without_changing_cycle(env,monkeypatch):
    db,client,_=env
    change=upgrade(client)
    monkeypatch.setattr(payments,'now_utc',lambda:END+timedelta(seconds=1))
    payments.confirm_subscription_payment(db,change['payment_id'])
    assert db.get(SubscriptionChange,change['id']).status=='REVIEW_REQUIRED'
    assert db.get(TenantSubscription,'sub-1').id_version_plan==1
    assert db.get(SubscriptionPayment,change['payment_id']).estado=='PAGADO'


@pytest.mark.parametrize('cancel',[False,True])
def test_scheduled_change_and_cancel_only_at_effective_date(env,cancel):
    db,client,_=env
    path='/api/v1/subscriptions/cancellation' if cancel else '/api/v1/subscriptions/changes'
    body={'idempotency_key':'scheduled-key'}
    if not cancel: body.update(plan_version_id=3,mode='NEXT_CYCLE')
    r=client.post(path,json=body);assert r.status_code==201,r.text
    assert utc(datetime.fromisoformat(r.json()['effective_at']))==END
    assert changes.process_cycle(db,1,END-timedelta(microseconds=1))==0
    sub=db.get(TenantSubscription,'sub-1')
    assert sub.id_version_plan==1 and sub.estado=='ACTIVE'
    assert changes.process_cycle(db,1,END)==(1 if cancel else 0)
    assert sub.estado==('CANCELLED' if cancel else 'ACTIVE')
    assert sub.id_version_plan==1
    assert utc(sub.fecha_inicio)==START and utc(sub.fecha_fin)==END
    if not cancel:
        assert db.get(SubscriptionChange,r.json()['id']).status=='WAITING_RENEWAL'
    assert changes.process_cycle(db,1,END)==0
    assert db.get(TenantSubscription,'sub-2').estado=='ACTIVE'


def test_catalog_edit_keeps_contracted_and_charged_version(env):
    db,client,_=env
    change=upgrade(client)
    version=db.get(VersionPlan,1)
    payload=VersionCreate(version_base=1,nombre='Editado',precio_mensual='250.00',moneda='BOB',ciclo='MENSUAL',
        servicios_incluidos=['AGENDA_TELECONSULTA'],limite_medicos=10,limite_sedes=None,limite_consultas=None,
        tarifas_excedentes=[],demora_pago_dias=0)
    result=catalog.new_version(db,1,payload,90,None)
    assert result.version.id!=version.id
    sub=payments.get_current_subscription(db,1)
    assert sub.plan_version_id==1 and sub.version.precio_mensual==Decimal('200.00')
    payment=db.get(SubscriptionPayment,change['payment_id'])
    assert payment.id_version_plan==2 and payment.plan_canonico.precio_mensual==Decimal('500.00')
    request=db.get(SubscriptionChange,change['id'])
    assert request.source_version_id==1 and request.target_version_id==2


def test_tenant_scope_idempotency_and_permission(env):
    db,client,_=env
    change=upgrade(client)
    assert client.get('/api/v1/subscriptions/changes',headers={'X-Test-Actor':'2'}).json()==[]
    assert client.post('/api/v1/subscriptions/checkout/'+change['payment_id']+'/synchronize',
                       headers={'X-Test-Actor':'2'}).status_code==404
    assert client.post('/api/v1/subscriptions/cancellation',json={'idempotency_key':'cancel-key'},
                       headers={'X-Test-Actor':'3'}).status_code==403
    request=db.get(SubscriptionChange,change['id'])
    repeat=client.post('/api/v1/subscriptions/changes',json={'plan_version_id':2,'mode':'IMMEDIATE',
        'idempotency_key':'upgrade-key-1','quote_token':'ignored-on-identical-retry'})
    assert repeat.status_code==201 and repeat.json()['id']==request.id
    assert client.post('/api/v1/subscriptions/cancellation',json={'idempotency_key':'cancel-other'}).status_code==409


def test_tampered_quote_and_injected_amount_rejected(env):
    _,client,_=env
    r=client.post('/api/v1/subscriptions/changes',json={'plan_version_id':2,'mode':'IMMEDIATE',
        'idempotency_key':'tamper-key','quote_token':'tampered'})
    assert r.status_code==409
    assert client.post('/api/v1/subscriptions/quote',json={'plan_version_id':2,'amount':'0.01'}).status_code==422


def test_wrong_gateway_amount_does_not_activate(env):
    db,client,_=env
    change=upgrade(client);payment=db.get(SubscriptionPayment,change['payment_id'])
    with pytest.raises(Exception):
        payments.verified_payment(db,payment,{'id':payment.stripe_session_id,'currency':'bob',
            'payment_status':'paid','amount_total':1})
    assert db.get(TenantSubscription,'sub-1').id_version_plan==1
    assert payment.estado=='PENDING'


def test_monthly_anchor_and_rounding():
    assert next_month(START,31)==END
    assert next_month(END,31)==datetime(2026,3,31,tzinfo=timezone.utc)
    assert adjustment('200.00','500.00',START,END,NOW)==Decimal('150.00')
    assert adjustment('0.00','0.01',START,END,NOW)==Decimal('0.01')


def test_worker_executes_due_actions_and_repeats_safely(env):
    db,client,sessions=env
    r=client.post('/api/v1/subscriptions/cancellation',json={'idempotency_key':'worker-cancel'})
    assert r.status_code==201
    from app.modules.tenants.subscription_changes.worker import run_due
    assert run_due(sessions,END-timedelta(microseconds=1))==0
    assert run_due(sessions,END)==1
    assert run_due(sessions,END)==0
    db.expire_all()
    assert db.get(TenantSubscription,'sub-1').estado=='CANCELLED'
    assert db.get(TenantSubscription,'sub-2').estado=='ACTIVE'


def test_prepaid_renewal_waits_for_boundary_and_is_not_charged_twice(env):
    db,client,sessions=env
    r=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':1,'cycle':'MENSUAL'})
    assert r.status_code==201
    payments.confirm_subscription_payment(db,r.json()['id_pago'])
    assert utc(db.get(TenantSubscription,'sub-1').fecha_fin)==END
    repeat=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':1,'cycle':'MENSUAL'})
    assert repeat.status_code==409
    from app.modules.tenants.subscription_changes.worker import run_due
    run_due(sessions,END);db.expire_all()
    sub=db.get(TenantSubscription,'sub-1')
    assert utc(sub.fecha_inicio)==END
    assert utc(sub.fecha_fin)==datetime(2026,3,31,tzinfo=timezone.utc)


def test_zero_price_upgrade_applies_without_gateway_and_keeps_cycle(env):
    db,client,_=env
    target=db.get(VersionPlan,2);target.precio_mensual=Decimal('200.00');db.commit()
    q=client.post('/api/v1/subscriptions/quote',json={'plan_version_id':2})
    assert q.status_code==200 and q.json()['amount']=='0.00'
    r=client.post('/api/v1/subscriptions/changes',json={'plan_version_id':2,'mode':'IMMEDIATE',
        'idempotency_key':'free-upgrade','quote_token':q.json()['quote_token']})
    assert r.status_code==201 and r.json()['status']=='APPLIED' and r.json()['payment_id'] is None
    assert utc(db.get(TenantSubscription,'sub-1').fecha_fin)==END


def test_global_admin_cannot_act_as_entity_admin(env):
    _,client,_=env
    r=client.post('/api/v1/subscriptions/cancellation',json={'idempotency_key':'global-admin'},
                  headers={'X-Test-Actor':'90','X-Tenant-ID':'1'})
    assert r.status_code==403


def test_integrated_migration_graph_has_one_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    root=Path(__file__).resolve().parents[1]
    config=Config(str(root/'alembic.ini'));config.set_main_option('script_location',str(root/'alembic'))
    assert ScriptDirectory.from_config(config).get_heads()==['cu35_cu18_convergencia_023']
    script=ScriptDirectory.from_config(config)
    assert script.get_revision('cu35_integracion_022').down_revision=='cu06_servicios_clinica_021'
    assert script.get_revision('cu35_cu18_convergencia_023').down_revision==(
        'merge_cu18_asistencia_022','cu35_integracion_022')


def test_deployable_app_has_no_manual_demo_routes():
    from app.main import app
    paths=app.openapi()['paths']
    assert not any('__cu35_demo' in path for path in paths)
    assert '/api/v1/subscriptions/quote' in paths
    assert '/api/v1/subscriptions/changes' in paths
    assert '/api/v1/subscriptions/cancellation' in paths


@pytest.mark.parametrize('table', [None,'pacientes','recetas','tenant_requests'])
def test_audit_clinical_events_still_require_tenant(env,table):
    from app.modules.auth.models import Auditoria
    from sqlalchemy.exc import IntegrityError
    db,_,_=env
    db.add(Auditoria(id_usuario=90,id_clinica=None,tabla_afectada=table,accion='INSERT'))
    with pytest.raises(IntegrityError): db.flush()
    db.rollback()


def test_zero_limit_rejects_registered_doctor_and_unknown_sedes_are_not_zero(env):
    from app.modules.appointments.models import Medico
    db,client,_=env
    db.add(Medico(id_medico=10,id_usuario=3,id_clinica=1,matricula_profesional='TEST',estado='ACTIVO'))
    target=db.get(VersionPlan,3);target.limite_medicos=0;db.commit()
    body={'plan_version_id':3,'mode':'NEXT_CYCLE','idempotency_key':'limit-zero'}
    assert client.post('/api/v1/subscriptions/changes',json=body).status_code==409
    target.limite_medicos=5;target.limite_sedes=1;db.commit()
    r=client.post('/api/v1/subscriptions/changes',json=body)
    assert r.status_code==409 and r.json()['detail']['code']=='SEDE_USAGE_UNAVAILABLE'


def test_scheduler_is_explicitly_opt_in_and_registered_without_starting_it(env):
    from app.modules.tenants.subscription_changes import worker
    from app.core.config import settings
    from unittest.mock import MagicMock
    scheduler=MagicMock()
    with patch.object(settings,'SUBSCRIPTION_CYCLE_WORKER_ENABLED',True), patch(
        'apscheduler.schedulers.background.BackgroundScheduler',return_value=scheduler):
        worker.start();worker.start()
        scheduler.start.assert_called_once()
        assert scheduler.add_job.call_args.kwargs['seconds']==60
        worker.stop();scheduler.shutdown.assert_called_once_with(wait=False)


def test_real_auth_blocks_only_cancelled_tenant_clinical_access_at_boundary(env,monkeypatch):
    from datetime import date
    from app.core.security import hash_password
    from app.modules.auth.router import router as auth_router
    from app.modules.medical_records.patient_profile.router import router as patient_router
    from app.modules.communications.router import router as communications_router
    from app.modules.medical_records.triage.router import router as triage_router
    from app.modules.medical_records.models import Paciente
    db,client,_=env
    paid=upgrade(client)
    payments.confirm_subscription_payment(db,paid['payment_id'])
    password='synthetic-CU35-password-123'
    for uid in (1,2):
        user=db.get(Usuario,uid);user.correo=f'cu35-{uid}@example.com';user.password_hash=hash_password(password)
    db.add(Paciente(id_paciente=10,id_clinica=1,nombres='Conservado',apellidos='CU35',ci='TEST-10',
        fecha_nacimiento=date(1990,1,1),genero='M',telefono='70000000',estado='ACTIVO'))
    db.commit()
    client.app.include_router(auth_router);client.app.include_router(patient_router)
    client.app.include_router(communications_router)
    client.app.include_router(triage_router)
    client.app.dependency_overrides.pop(get_current_user)
    headers=[]
    for uid in (1,2):
        login=client.post('/auth/login',json={'correo':f'cu35-{uid}@example.com','password':password})
        assert login.status_code==200,login.text
        headers.append({'Authorization':'Bearer '+login.json()['access_token']})
    first,second=headers
    result=client.post('/api/v1/subscriptions/cancellation',json={'idempotency_key':'access-cancel'},headers=first)
    assert result.status_code==201,result.text
    monkeypatch.setattr(payments,'now_utc',lambda:END-timedelta(microseconds=1))
    assert client.get('/api/v1/pacientes',headers=first).status_code==200
    monkeypatch.setattr(payments,'now_utc',lambda:END)
    blocked=client.get('/api/v1/pacientes',headers=first)
    assert blocked.status_code==403 and blocked.headers['X-Subscription-Status']=='CANCELLED'
    assert client.get('/api/v1/pacientes',headers=second).status_code==200
    # Legacy realtime endpoints must not provide an anonymous bypass.
    assert client.get('/citas/1/chat/realtime',headers=first).status_code==403
    assert client.get('/citas/1/chat/realtime').status_code==401
    assert client.get('/citas/1/chat/realtime',headers=second).status_code==404
    assert client.post('/triaje/preliminar',json={},headers=first).status_code==403
    assert client.post('/triaje/preliminar',json={}).status_code==401
    changes.process_cycle(db,1,END)
    assert client.get('/api/v1/subscriptions/current',headers=first).json()['estado']=='CANCELLED'
    assert client.get('/api/v1/subscription-payments',headers=first).status_code==200
    receipt=client.get('/api/v1/subscription-payments/'+paid['payment_id']+'/receipt',headers=first)
    assert receipt.status_code==200 and receipt.json()['plan_version_id']==2
    pdf=client.get('/api/v1/subscription-payments/'+paid['payment_id']+'/receipt/pdf',headers=first)
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    assert client.get('/auth/me',headers=first).status_code==200
    assert client.post('/auth/login',json={'correo':'cu35-1@example.com','password':password}).status_code==200
    assert db.get(Paciente,10).nombres=='Conservado'
    assert db.get(Clinica,1).estado=='ACTIVE'


def test_cancel_rejects_client_effective_date(env):
    _,client,_=env
    r=client.post('/api/v1/subscriptions/cancellation',json={
        'idempotency_key':'no-immediate-cancel','effective_at':NOW.isoformat()})
    assert r.status_code==422


def test_catalog_target_edition_does_not_reprice_pending_upgrade(env):
    db,client,_=env
    change=upgrade(client)
    data=VersionCreate(version_base=1,nombre='Nueva oferta',precio_mensual='700.00',moneda='BOB',ciclo='MENSUAL',
        servicios_incluidos=['AGENDA_TELECONSULTA'],limite_medicos=20,limite_sedes=None,limite_consultas=None,
        tarifas_excedentes=[],demora_pago_dias=0)
    catalog.new_version(db,2,data,90,None)
    payments.confirm_subscription_payment(db,change['payment_id'])
    current=payments.get_current_subscription(db,1)
    assert current.plan_version_id==2 and current.version.precio_mensual==Decimal('500.00')
    history=payments.list_subscription_payments(db,1,1,20)
    assert history.items[0].plan_version_id==2 and history.items[0].monto==Decimal('150.00')


def test_first_checkout_sets_anchor_for_approved_unpaid_subscription(env,monkeypatch):
    db,client,_=env
    sub=db.get(TenantSubscription,'sub-1');sub.estado='TRIALING';sub.billing_anchor_day=None
    sub.fecha_inicio=datetime(2026,1,1,tzinfo=timezone.utc);sub.fecha_fin=sub.fecha_inicio
    db.commit();monkeypatch.setattr(payments,'now_utc',lambda:START)
    r=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':1,'cycle':'MENSUAL'})
    assert r.status_code==201,r.text
    payments.confirm_subscription_payment(db,r.json()['id_pago'])
    assert sub.billing_anchor_day==31 and utc(sub.fecha_fin)==END


def publish(db, plan_id, price):
    old=db.get(Plan,plan_id)
    v=db.scalar(select(VersionPlan).where(VersionPlan.plan_id==plan_id,VersionPlan.numero==old.version_actual))
    return catalog.new_version(db,plan_id,VersionCreate(version_base=v.numero,nombre=v.nombre,
        precio_mensual=price,moneda='BOB',ciclo='MENSUAL',servicios_incluidos=v.servicios_incluidos,
        limite_medicos=v.limite_medicos,limite_sedes=v.limite_sedes,limite_consultas=v.limite_consultas,
        tarifas_excedentes=[],demora_pago_dias=0),90,None).version


def test_renewal_accepts_published_version_preserving_current_and_paid_history(env):
    db,client,sessions=env
    accepted=publish(db,1,'250.00')
    assert client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':1,'cycle':'MENSUAL'}).status_code==422
    offered=client.get('/api/v1/subscriptions/plans').json()
    assert any(v['id']==accepted.id and v['precio_mensual']=='250.00' for v in offered)
    r=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':accepted.id,'cycle':'MENSUAL'})
    assert r.status_code==201,r.text
    payment=db.get(SubscriptionPayment,r.json()['id_pago'])
    assert payment.id_version_plan==accepted.id and payment.monto==Decimal('250.00')
    publish(db,1,'300.00')  # Offer changes after acceptance must not reprice the payment.
    payments.confirm_subscription_payment(db,payment.id_pago_suscripcion)
    assert payment.application_status=='SCHEDULED'
    sub=db.get(TenantSubscription,'sub-1')
    assert sub.id_version_plan==1 and utc(sub.fecha_fin)==END
    from app.modules.tenants.subscription_changes.worker import run_due
    assert run_due(sessions,END-timedelta(microseconds=1))==0
    run_due(sessions,END);db.expire_all()
    sub=db.get(TenantSubscription,'sub-1')
    assert sub.id_version_plan==accepted.id and utc(sub.fecha_inicio)==END
    assert utc(sub.fecha_fin)==datetime(2026,3,31,tzinfo=timezone.utc)
    row=sub.row_version
    payments.confirm_subscription_payment(db,payment.id_pago_suscripcion)
    run_due(sessions,END)
    assert sub.row_version==row
    history=payments.list_subscription_payments(db,1,1,20).items[0]
    assert history.plan_version_id==accepted.id and history.version.precio_mensual==Decimal('250.00')
    assert history.application_status=='APPLIED'


@pytest.mark.parametrize('failed',[False,True])
def test_unpaid_or_failed_renewal_never_advances_paid_cycle(env,failed):
    db,client,_=env
    version=publish(db,1,'250.00')
    if failed:
        r=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':version.id,'cycle':'MENSUAL'})
        payment=db.get(SubscriptionPayment,r.json()['id_pago'])
        import json
        with patch.object(payments,'verificar_firma_stripe'):
            payments.procesar_webhook_suscripcion(db,json.dumps({'type':'checkout.session.async_payment_failed',
                'data':{'object':{'id':payment.stripe_session_id}}}).encode(),'test')
        assert payment.estado=='FALLIDO'
    changes.process_cycle(db,1,END)
    sub=db.get(TenantSubscription,'sub-1')
    assert sub.id_version_plan==1 and utc(sub.fecha_inicio)==START and utc(sub.fecha_fin)==END


def test_scheduled_cancellation_blocks_renewal_before_and_after_boundary(env,monkeypatch):
    db,client,_=env
    assert client.post('/api/v1/subscriptions/cancellation',json={'idempotency_key':'cancel-renewal'}).status_code==201
    for now in (NOW,END):
        monkeypatch.setattr(payments,'now_utc',lambda:now)
        assert client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':1,'cycle':'MENSUAL'}).status_code==409
    assert db.scalar(select(SubscriptionPayment)) is None


def test_scheduled_change_renews_exact_requested_snapshot_only_after_payment(env,monkeypatch):
    db,client,_=env
    r=client.post('/api/v1/subscriptions/changes',json={'plan_version_id':3,'mode':'NEXT_CYCLE','idempotency_key':'renew-destination'})
    assert r.status_code==201
    assert r.json()['target_version']['precio_mensual']=='100.00'
    published=publish(db,3,'150.00')
    assert client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':published.id,'cycle':'MENSUAL'}).status_code==409
    renewal=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':3,'cycle':'MENSUAL'})
    assert renewal.status_code==201,renewal.text
    payments.confirm_subscription_payment(db,renewal.json()['id_pago'])
    assert db.get(TenantSubscription,'sub-1').id_version_plan==1
    assert changes.process_cycle(db,1,END-timedelta(microseconds=1))==0
    assert changes.process_cycle(db,1,END)==1
    sub=db.get(TenantSubscription,'sub-1')
    assert sub.id_version_plan==3 and sub.estado=='ACTIVE' and utc(sub.fecha_inicio)==END
    assert utc(sub.fecha_fin)==datetime(2026,3,31,tzinfo=timezone.utc)
    assert db.get(SubscriptionChange,r.json()['id']).status=='APPLIED'
    assert db.get(SubscriptionPayment,renewal.json()['id_pago']).monto==Decimal('100.00')
    assert changes.process_cycle(db,1,END)==0


def test_failed_scheduled_renewal_can_retry_without_losing_destination(env,monkeypatch):
    db,client,_=env
    r=client.post('/api/v1/subscriptions/changes',json={'plan_version_id':3,'mode':'NEXT_CYCLE','idempotency_key':'retry-destination'})
    checkout=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':3,'cycle':'MENSUAL'})
    payment=db.get(SubscriptionPayment,checkout.json()['id_pago'])
    import json
    with patch.object(payments,'verificar_firma_stripe'):
        payments.procesar_webhook_suscripcion(db,json.dumps({'type':'checkout.session.async_payment_failed',
            'data':{'object':{'id':payment.stripe_session_id}}}).encode(),'test')
    assert db.get(SubscriptionChange,r.json()['id']).status=='WAITING_RENEWAL'
    changes.process_cycle(db,1,END)
    assert db.get(TenantSubscription,'sub-1').id_version_plan==1
    monkeypatch.setattr(payments,'now_utc',lambda:END)
    retry=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':3,'cycle':'MENSUAL'})
    assert retry.status_code==201 and retry.json()['id_pago']!=payment.id_pago_suscripcion
    payments.confirm_subscription_payment(db,retry.json()['id_pago'])
    assert db.get(TenantSubscription,'sub-1').id_version_plan==3
    assert db.get(SubscriptionChange,r.json()['id']).status=='APPLIED'



@pytest.mark.parametrize('confirmed_at',[NOW,END])
def test_late_old_payment_cannot_bypass_pending_cancellation(env,monkeypatch,confirmed_at):
    db,client,_=env
    checkout=client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':1,'cycle':'MENSUAL'})
    old=db.get(SubscriptionPayment,checkout.json()['id_pago'])
    old.estado='CANCELADO';old.application_status='NOT_APPLIED';db.commit()
    cancel=client.post('/api/v1/subscriptions/cancellation',json={'idempotency_key':'cancel-after-expiry'})
    assert cancel.status_code==201,cancel.text
    monkeypatch.setattr(payments,'now_utc',lambda:confirmed_at)
    payments.confirm_subscription_payment(db,old.id_pago_suscripcion)
    assert old.estado=='PAGADO' and old.application_status=='REVIEW_REQUIRED'
    sub=db.get(TenantSubscription,'sub-1')
    assert utc(sub.fecha_fin)==END
    changes.process_cycle(db,1,END)
    assert sub.estado=='CANCELLED'
