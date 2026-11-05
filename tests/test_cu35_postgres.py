"""Real migrations and concurrent sessions, restricted to local disposable databases."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import re
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text, func, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.modules.auth.models import Clinica, Rol, Usuario, Plan, VersionPlan, Auditoria
from app.modules.auth.planes import service as catalog
from app.modules.auth.planes.schemas import VersionCreate
from app.modules.tenants.models import TenantSubscription, SubscriptionPayment, SubscriptionChange
from app.modules.tenants.subscription_payments import service as payments
from app.modules.tenants.subscription_changes import service as changes, worker
from app.modules.tenants.billing import utc

START = datetime(2026,1,31,tzinfo=timezone.utc)
END = datetime(2026,2,28,tzinfo=timezone.utc)
NOW = datetime(2026,2,14,tzinfo=timezone.utc)


def local_url():
    raw = os.environ.get('CU35_LOCAL_DATABASE_URL','')
    if not raw:
        pytest.skip('Set CU35_LOCAL_DATABASE_URL to an isolated local PostgreSQL database')
    url = make_url(raw)
    if (url.host not in ('127.0.0.1','localhost') or not re.fullmatch(r'cu34_test_[A-Za-z0-9_]+',url.database or '')
            or url.get_backend_name() != 'postgresql' or url.query):
        pytest.fail('Only explicit local cu34_test_* PostgreSQL databases are allowed')
    return raw


def migrate_database(database, target, mappings=None):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root/'alembic.ini'))
    config.set_main_option('script_location',str(root/'alembic'))
    if mappings:
        from argparse import Namespace
        import json
        config.cmd_opts = Namespace(x=[key+'='+json.dumps(value) for key,value in mappings.items()])
    from app.core.config import settings
    previous = settings.DB_NAME
    settings.DB_NAME = database
    try:
        command.upgrade(config,target)
    finally:
        settings.DB_NAME = previous



@contextmanager
def isolated_database(target='cu35_cu18_convergencia_023'):
    raw = local_url()
    url = make_url(raw)
    database = 'cu34_test_cu35_'+uuid4().hex
    template = ('cu34_test_cu35_base' if target == '62b0d532ee0a' else
                'cu34_test_cu35_review_base' if target == 'cu06_servicios_clinica_021' else
                'cu34_test_cu35_cu18_base' if target == 'merge_cu18_asistencia_022' else url.database)
    root = create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT')
    with root.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{database}" TEMPLATE "{template}"')
    engine = create_engine(url.set(database=database))
    try:
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT version_num FROM alembic_version')) == target
        yield engine,database
    finally:
        engine.dispose()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{database}"')
        root.dispose()


def seed(db, subscriptions=True, first_price='200.00'):
    for i in (1,2,3):
        db.add(Clinica(id_clinica=i,nombre=f'Prueba PG {i}',estado='ACTIVE'))
    db.flush()
    for i in (1,2,3):
        db.add(Rol(id_rol=i+100,id_clinica=i,nombre='ADMIN',estado='ACTIVO'))
    db.add(Rol(id_rol=190,id_clinica=None,nombre='Super Administrador',estado='ACTIVO'))
    db.flush()
    for i in (1,2,3,90):
        db.add(Usuario(id_usuario=i,id_clinica=i if i!=90 else None,id_rol=i+100,nombres='Prueba',
            apellidos='PG',correo=f'pg-cu35-{i}@example.test',password_hash='not-a-login',estado='ACTIVO'))
    db.flush()
    for pid,price,doctors,consults in ((1,first_price,10,100),(2,'500.00',20,300),(3,'100.00',5,50)):
        db.add(Plan(id=pid,codigo=f'PG{pid}',activo=True,version_actual=1));db.flush()
        db.add(VersionPlan(id=pid,plan_id=pid,numero=1,nombre=f'Plan {pid}',precio_mensual=price,
            moneda='BOB',ciclo='MENSUAL',limite_medicos=doctors,limite_sedes=None,limite_consultas=consults,
            servicios_incluidos=['AGENDA_TELECONSULTA'],tarifas_excedentes=[],demora_pago_dias=0,creado_por=90))
    db.flush()
    # ORM fixtures with explicit IDs must also advance PostgreSQL sequences.
    for table,column in (('planes','id'),('versiones_plan','id'),('clinicas','id_clinica'),('roles','id_rol'),('usuarios','id_usuario')):
        db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}','{column}'),(SELECT max({column}) FROM {table}))"))
    if subscriptions:
        for i in (1,2,3):
            db.add(TenantSubscription(id_suscripcion=f'pg-sub-{i}',id_clinica=i,id_version_plan=1,
                ciclo='MONTHLY',fecha_inicio=START,fecha_fin=END,billing_anchor_day=31,dias_gracia=0,estado='ACTIVE',row_version=1))
    db.commit()


@pytest.fixture
def pg(monkeypatch):
    with isolated_database() as (engine,database):
        sessions = sessionmaker(engine,expire_on_commit=False)
        with sessions() as db:
            seed(db)
        monkeypatch.setattr(payments,'now_utc',lambda:NOW)
        monkeypatch.setattr(payments,'stripe_habilitado',lambda:False)
        yield engine,sessions


def concurrent(fn):
    barrier=Barrier(2)
    def run(i):
        barrier.wait(timeout=10)
        return fn(i)
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(run,(0,1)))


def test_migrated_schema_and_snapshot_history(pg):
    engine,sessions=pg
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='cu35_cu18_convergencia_023'
        for table in ('tenant_subscriptions','subscription_payments','tenant_requests'):
            fk=next(f for f in inspect(conn).get_foreign_keys(table) if f['constrained_columns']==['id_version_plan'])
            assert fk['referred_table']=='versiones_plan' and fk['options']['ondelete']=='RESTRICT'
    with sessions() as db:
        q=changes.quote(db,1,2)
        change=changes.request_change(db,1,db.get(Usuario,1),'pg-upgrade','IMMEDIATE',2,q.quote_token)
        published=catalog.new_version(db,1,VersionCreate(version_base=1,nombre='Oferta 250',precio_mensual='250.00',
            moneda='BOB',ciclo='MENSUAL',limite_medicos=10,limite_sedes=None,limite_consultas=100,
            servicios_incluidos=['AGENDA_TELECONSULTA'],tarifas_excedentes=[],demora_pago_dias=0),90,None)
        assert published.version.id!=1
        assert payments.get_current_subscription(db,1).version.precio_mensual==Decimal('200.00')
        payment=db.get(SubscriptionPayment,change.payment_id)
        assert payment.id_version_plan==2 and payment.monto==Decimal('150.00')
        assert payment.plan_canonico.precio_mensual==Decimal('500.00')


def test_concurrent_same_key_creates_one_request(pg):
    _,sessions=pg
    def request(_):
        with sessions() as db:
            return changes.request_change(db,1,db.get(Usuario,1),'same-key-pg','NEXT_CYCLE',3).id
    assert len(set(concurrent(request)))==1
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(SubscriptionChange))==1


def test_concurrent_different_keys_only_one_pending(pg):
    _,sessions=pg
    def request(i):
        with sessions() as db:
            try:
                changes.request_change(db,1,db.get(Usuario,1),'distinct-key-'+str(i),'NEXT_CYCLE',3)
                return 201
            except HTTPException as exc:
                return exc.status_code
    assert sorted(concurrent(request))==[201,409]


def test_concurrent_payment_confirmation_applies_once(pg):
    _,sessions=pg
    with sessions() as db:
        q=changes.quote(db,1,2)
        request=changes.request_change(db,1,db.get(Usuario,1),'paid-key-pg','IMMEDIATE',2,q.quote_token)
        payment_id=request.payment_id
    def confirm(_):
        with sessions() as db:
            return payments.confirm_subscription_payment(db,payment_id).estado
    assert concurrent(confirm)==['PAGADO','PAGADO']
    with sessions() as db:
        sub=db.get(TenantSubscription,'pg-sub-1')
        assert sub.id_version_plan==2 and sub.row_version==2 and sub.fecha_fin==END
        assert db.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.accion=='APLICAR_CAMBIO_SUSCRIPCION'))==1
        with pytest.raises(HTTPException) as err:
            payments.sincronizar_checkout_suscripcion(db,2,payment_id)
        assert err.value.status_code==404


def prepare_due(sessions):
    with sessions() as db:
        changes.request_change(db,1,db.get(Usuario,1),'next-key-pg','NEXT_CYCLE',3)
        changes.request_change(db,2,db.get(Usuario,2),'cancel-key-pg','CANCEL')
        checkout=payments.create_subscription_checkout(db,1,db.get(Usuario,1),3,'MENSUAL')
        payments.confirm_subscription_payment(db,checkout.id_pago)


def verify_due(sessions):
    with sessions() as db:
        first=db.get(TenantSubscription,'pg-sub-1'); second=db.get(TenantSubscription,'pg-sub-2')
        assert first.id_version_plan==3 and first.fecha_inicio==END
        assert first.fecha_fin==datetime(2026,3,31,tzinfo=timezone.utc) and first.row_version==2
        assert second.estado=='CANCELLED' and second.fecha_fin==END and second.row_version==2
        assert db.get(TenantSubscription,'pg-sub-3').id_version_plan==1
        assert db.scalar(select(func.count()).select_from(SubscriptionChange).where(SubscriptionChange.status=='APPLIED'))==2
        assert db.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.accion=='APLICAR_CAMBIO_SUSCRIPCION'))==2


def test_concurrent_workers_and_repeated_closing(pg):
    _,sessions=pg
    prepare_due(sessions)
    assert worker.run_due(sessions,END-timedelta(microseconds=1))==0
    assert sum(concurrent(lambda _:worker.run_due(sessions,END)))==2
    verify_due(sessions)
    assert worker.run_due(sessions,END)==0
    verify_due(sessions)


def test_actual_scheduler_opt_in_only_in_test(pg,monkeypatch):
    from app.core.config import settings
    _,sessions=pg
    prepare_due(sessions)
    clock={'now':END-timedelta(microseconds=1)}
    called=Event(); counts=[]
    original=worker.run_due
    def run():
        counts.append(original(sessions,clock['now']))
        called.set()
    monkeypatch.setattr(worker,'run_due',run)
    monkeypatch.setattr(settings,'SUBSCRIPTION_CYCLE_WORKER_ENABLED',True)
    worker.start()
    try:
        job=worker.scheduler.get_job('subscription-cycle')
        assert job is not None
        for now,expected in ((END-timedelta(microseconds=1),0),(END,2),(END,0)):
            called.clear();clock['now']=now
            job.modify(next_run_time=datetime.now(timezone.utc))
            assert called.wait(15),'Scheduler did not finish its due run'
            assert counts[-1]==expected
        verify_due(sessions)
    finally:
        worker.stop()


def test_legacy_preflight_and_independent_historical_mapping():
    with isolated_database('cu06_servicios_clinica_021') as (engine,database):
        sessions=sessionmaker(engine)
        with sessions() as db:
            seed(db,subscriptions=False)
            db.execute(text("INSERT INTO plan_versions (id_plan_version,nombre,precio_mensual,moneda,limite_medicos,limite_consultas_mes) VALUES ('old-A','same-name',200,'BOB',10,100),('old-B','same-name',500,'BOB',20,300)"))
            db.execute(text("INSERT INTO tenant_subscriptions (id_suscripcion,id_clinica,id_plan_version,id_version_plan,ciclo,fecha_inicio,fecha_fin) VALUES ('legacy-sub',1,'old-A',1,'MONTHLY',:start,:end)"),{'start':START,'end':END})
            db.execute(text("INSERT INTO subscription_payments (id_pago_suscripcion,id_suscripcion,id_clinica,id_usuario,id_plan_version,id_version_plan,ciclo,monto,moneda,estado) VALUES ('legacy-pay','legacy-sub',1,1,'old-B',1,'MONTHLY',500,'BOB','PAGADO')"))
            db.commit()
        with pytest.raises(RuntimeError,match='requiere subscription_version_map'):
            migrate_database(database,'cu35_integracion_022')
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='cu06_servicios_clinica_021'
            assert 'billing_anchor_day' not in {c['name'] for c in inspect(conn).get_columns('tenant_subscriptions')}
        migrate_database(database,'cu35_integracion_022',{'subscription_version_map':{'legacy-sub':1},'payment_version_map':{'legacy-pay':2},'billing_anchor_map':{'legacy-sub':31}})
        with sessions() as db:
            sub=db.get(TenantSubscription,'legacy-sub'); payment=db.get(SubscriptionPayment,'legacy-pay')
            assert sub.id_version_plan==1 and payment.id_version_plan==2
            assert sub.id_plan_version=='old-A' and payment.id_plan_version=='old-B'
            assert payment.monto==Decimal('500.00') and sub.billing_anchor_day==31
            assert sub.fecha_inicio==START and sub.fecha_fin==END


def test_direct_upgrade_refuses_name_backfill_before_shared_020():
    with isolated_database('62b0d532ee0a') as (engine,database):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO plan_versions (id_plan_version,nombre,precio_mensual) VALUES ('guard-legacy','same-name',200)"))
        with pytest.raises(RuntimeError,match='detener antes de 020'):
            migrate_database(database,'cu35_integracion_022')
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='62b0d532ee0a'
            assert not inspect(conn).has_table('legacy_plan_version_mappings')


def test_cu18_populated_upgrade_requires_anchor_and_preserves_exact_snapshots():
    """Anonymous shape of the observed canonical subscription/payment, no real IDs."""
    with isolated_database('merge_cu18_asistencia_022') as (engine,database):
        sessions=sessionmaker(engine)
        start=datetime(2026,11,5,5,29,41,470415,tzinfo=timezone.utc)
        end=datetime(2026,12,5,5,29,41,470415,tzinfo=timezone.utc)
        with sessions() as db:
            seed(db,subscriptions=False,first_price='125.00')
            db.execute(text("INSERT INTO tenant_subscriptions (id_suscripcion,id_clinica,id_version_plan,ciclo,fecha_inicio,fecha_fin,estado,row_version) VALUES ('canonical-existing',1,1,'MONTHLY',:start,:end,'ACTIVE',2)"),{'start':start,'end':end})
            db.execute(text("INSERT INTO subscription_payments (id_pago_suscripcion,id_suscripcion,id_clinica,id_usuario,id_version_plan,ciclo,monto,moneda,estado,fecha_pago) VALUES ('canonical-paid','canonical-existing',1,1,1,'MONTHLY',125,'BOB','PAGADO',:paid)"),{'paid':start-timedelta(microseconds=169141)})
            db.commit()
        with pytest.raises(RuntimeError,match='billing_anchor_map'):
            migrate_database(database,'head')
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='merge_cu18_asistencia_022'
            assert 'billing_anchor_day' not in {c['name'] for c in inspect(conn).get_columns('tenant_subscriptions')}
        # Explicit fixture anchor, NOT an inferred/approved mapping for the shared DB.
        migrate_database(database,'head',{'billing_anchor_map':{'canonical-existing':5}})
        with sessions() as db:
            sub=db.get(TenantSubscription,'canonical-existing')
            payment=db.get(SubscriptionPayment,'canonical-paid')
            assert sub.id_version_plan==payment.id_version_plan==1
            assert sub.id_plan_version is None and payment.id_plan_version is None
            assert sub.fecha_inicio==start and sub.fecha_fin==end and sub.row_version==2
            assert sub.billing_anchor_day==5 and payment.monto==Decimal('125.00')
            assert payment.estado=='PAGADO' and payment.application_status=='APPLIED'
            assert payment.period_start is None and payment.period_end is None
            assert sub.plan_canonico.precio_mensual==Decimal('125.00')
            assert payment.plan_canonico.precio_mensual==Decimal('125.00')
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='cu35_cu18_convergencia_023'
            assert all(inspect(conn).has_table(t) for t in
                       ('evaluaciones_asistencia','interacciones_catalogo','alertas_interaccion','subscription_changes'))
