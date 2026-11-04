from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
import pytest
from sqlalchemy import func, select, text, inspect
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.modules.auth.models import Auditoria, Plan, VersionPlan
from app.modules.auth.planes.schemas import PlanCreate, VersionCreate
from app.modules.auth.planes import service
from conftest import migration

URL = '/api/v1/planes'


def test_real_auth_without_credentials_and_single_route_registration(client):
    from app.modules.auth.dependencies import get_current_user
    client.app.dependency_overrides.pop(get_current_user)
    assert client.get(URL).status_code == 401
    # Import only: no TestClient lifespan / backup scheduler startup.
    from app.main import app
    def flatten(router):
        for route in router.routes:
            original = getattr(route, 'original_router', None)
            if original is not None: yield from flatten(original)
            else: yield route
    routes = [(r.path, method) for r in flatten(app) if hasattr(r, 'methods') for method in r.methods if r.path.startswith(URL)]
    assert len(routes) == len(set(routes)) == 8


@pytest.mark.parametrize('actor,status', [(0,401),(101,403),(102,403),(103,403)])
@pytest.mark.parametrize('method,path,body', [
    ('get','',None),('get','/opciones',None),('get','/1',None),('get','/1/versiones',None),
    ('get','/1/versiones/1',None),('post','',{}),('post','/1/versiones',{}),('patch','/1/estado',{'activo':False})])
def test_all_operations_require_global_superadmin(client,actor,status,method,path,body):
    response = client.request(method,URL+path,headers={'X-Test-Actor':str(actor)},json=body)
    assert response.status_code == status


@pytest.mark.parametrize('field,value', [
    ('precio_mensual','-1'),('precio_mensual','NaN'),('precio_mensual','Infinity'),('precio_mensual','1.001'),
    ('precio_mensual',1.2),('precio_mensual','1e3'),('precio_mensual','1000000000000.00'),
    ('limite_medicos',-1),('limite_medicos',True),('limite_sedes',1.5),('limite_sedes','2'),
    ('demora_pago_dias',-1),('demora_pago_dias',1.5),('moneda','USD'),('ciclo','ANUAL'),
    ('nombre','  '),('servicios_incluidos',['UNKNOWN']),('servicios_incluidos',['LABORATORIO','LABORATORIO']),
    ('tarifas_excedentes',[{'recurso':'CONSULTAS','unidad':'CONSULTA','precio':'1.00'}]),
    ('tarifas_excedentes',[{'recurso':'MEDICOS','unidad':'CONSULTA','precio':'1.00'}]),
    ('tarifas_excedentes',[{'recurso':'MEDICOS','unidad':'MEDICO_CICLO_MENSUAL','precio':'NaN'}]),
    ('precio_anual','100.00'),('tenant_id',1)])
def test_validation(client,payload,field,value):
    payload[field]=value
    assert client.post(URL,json=payload).status_code == 422
    assert client.get(URL).json()['total'] == 0


@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_numeric_json_is_validation_error_not_server_error(client,payload,value):
    payload['precio_mensual']=value
    response=client.post(URL,content=json.dumps(payload),headers={'Content-Type':'application/json'})
    assert response.status_code==422, response.text
    assert isinstance(response.json()['detail'],list)
    assert client.get(URL).json()['total']==0


def test_create_precision_duplicates_search_pagination_and_audit(client,payload,engine):
    created=client.post(URL,json=payload)
    assert created.status_code == 201, created.text
    plan=created.json()
    assert plan['version']['precio_mensual']=='1234.56'
    assert plan['version']['tarifas_excedentes'][0]['precio']=='12.10'
    assert plan['version']['limite_consultas'] is None
    assert plan['version']['limite_sedes']==0
    assert client.post(URL,json=payload).json()['code']=='PLAN_CODE_EXISTS'
    for i in range(4):
        assert client.post(URL,json={**payload,'codigo':f'TEST_{i}'}).status_code==201
    page=client.get(URL,params={'q':'test_','per_page':2,'page':2}).json()
    assert page['total']==4 and len(page['items'])==2
    assert client.get(URL,params={'q':'%'}).json()['total']==0
    assert client.get(URL,params={'q':'Prueba'}).json()['total']==5
    with Session(engine) as db:
        events=db.scalars(select(Auditoria)).all()
        assert len(events)==5 and all(e.id_clinica is None for e in events)
        assert events[0].datos_nuevos['version']['precio_mensual']=='1234.56'
    assert client.get(URL+'/99999').status_code==404
    assert client.get(URL,params={'page':0}).status_code==422


def test_versions_stale_history_and_idempotent_deactivation(client,payload,engine):
    plan=client.post(URL,json=payload).json(); pid=plan['id']
    conditions={k:v for k,v in payload.items() if k!='codigo'}
    changed={**conditions,'precio_mensual':'0','nombre':'Versión gratuita','version_base':1}
    updated=client.post(f'{URL}/{pid}/versiones',json=changed)
    assert updated.status_code==201, updated.text
    assert updated.json()['version_actual']==2
    assert updated.json()['version']['precio_mensual']=='0.00'
    assert client.post(f'{URL}/{pid}/versiones',json=changed).json()['code']=='PLAN_STALE_VERSION'
    old=client.get(f'{URL}/{pid}/versiones/1').json()
    assert old['precio_mensual']=='1234.56' and old['id']==plan['version']['id']
    history=client.get(f'{URL}/{pid}/versiones',params={'page':1,'per_page':1}).json()
    assert history['total']==2 and history['items'][0]['numero']==2
    assert client.get(f'{URL}/{pid}/versiones/999').status_code==404
    for _ in range(2): assert client.patch(f'{URL}/{pid}/estado',json={'activo':False}).status_code==200
    assert client.get(URL,params={'estado':'ACTIVO'}).json()['total']==0
    assert client.get(URL,params={'estado':'INACTIVO'}).json()['total']==1
    assert client.post(f'{URL}/{pid}/versiones',json={**changed,'version_base':2}).json()['code']=='PLAN_INACTIVE'
    assert client.patch(f'{URL}/{pid}/estado',json={'activo':True}).status_code==422
    assert client.patch(f'{URL}/{pid}/estado',json={'activo':0}).status_code==422
    assert client.delete(f'{URL}/{pid}').status_code==405
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(VersionPlan))==2
        assert db.scalar(select(func.count()).select_from(Auditoria))==3


def test_audit_failure_rolls_back_creation_and_edit(client,payload,engine,monkeypatch):
    original=service.registrar_auditoria
    def fail(*args,**kwargs): raise RuntimeError('isolated audit failure')
    monkeypatch.setattr(service,'registrar_auditoria',fail)
    assert client.post(URL,json=payload).status_code==500
    assert client.get(URL).json()['total']==0
    monkeypatch.setattr(service,'registrar_auditoria',original)
    plan=client.post(URL,json=payload).json()
    monkeypatch.setattr(service,'registrar_auditoria',fail)
    data={k:v for k,v in payload.items() if k!='codigo'}
    assert client.post(f"{URL}/{plan['id']}/versiones",json={**data,'version_base':1}).status_code==500
    assert client.get(f"{URL}/{plan['id']}").json()['version_actual']==1
    assert client.patch(f"{URL}/{plan['id']}/estado",json={'activo':False}).status_code==500
    assert client.get(f"{URL}/{plan['id']}").json()['activo'] is True
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(VersionPlan))==1
        assert db.scalar(select(func.count()).select_from(Auditoria))==1


def test_postgresql_migration_immutability_and_constraints(pg_engine,payload):
    with Session(pg_engine) as db: plan=service.create(db,PlanCreate(**payload),100)
    for statement in ('UPDATE versiones_plan SET nombre=\'alterado\'', 'DELETE FROM versiones_plan'):
        with pytest.raises(DBAPIError), pg_engine.begin() as conn: conn.execute(text(statement))
    with pg_engine.connect() as conn:
        assert conn.scalar(text('SELECT nombre FROM versiones_plan'))==payload['nombre']
        assert inspect(conn).get_columns('versiones_plan')[0]['name']=='id'
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO auditoria (id_usuario,accion,tabla_afectada) VALUES(100,'INSERT','pacientes')"))
    with pytest.raises(RuntimeError,match='historial'), pg_engine.begin() as conn:
        module=migration(); module.op=Operations(MigrationContext.configure(conn)); module.downgrade()


def test_postgresql_empty_downgrade_upgrade(pg_engine):
    module=migration()
    with pg_engine.begin() as conn:
        module.op=Operations(MigrationContext.configure(conn)); module.downgrade()
        assert 'planes' not in inspect(conn).get_table_names()
        assert not next(c for c in inspect(conn).get_columns('auditoria') if c['name']=='id_clinica')['nullable']
        module.upgrade()
        assert {'planes','versiones_plan'} <= set(inspect(conn).get_table_names())


def test_postgresql_concurrent_versions(pg_engine,payload):
    with Session(pg_engine) as db: plan=service.create(db,PlanCreate(**payload),100)
    data={k:v for k,v in payload.items() if k!='codigo'}
    barrier=Barrier(2)
    def edit(price):
        with Session(pg_engine) as db:
            barrier.wait(timeout=10)
            try: return service.new_version(db,plan.id,VersionCreate(**{**data,'precio_mensual':price,'version_base':1}),100).version_actual
            except service.PlanError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(edit,['20.01','30.02']))
    assert sorted(map(str,results))==['2','PLAN_STALE_VERSION']
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count()).select_from(VersionPlan))==2
        assert db.scalar(select(func.count()).select_from(Auditoria))==2
        assert service.version_detail(db,plan.id,1).precio_mensual==PlanCreate(**payload).precio_mensual


def test_postgresql_concurrent_deactivation(pg_engine,payload):
    with Session(pg_engine) as db: plan=service.create(db,PlanCreate(**payload),100)
    barrier=Barrier(2)
    def deactivate(_):
        with Session(pg_engine) as db:
            barrier.wait(timeout=10)
            return service.deactivate(db,plan.id,100).activo
    with ThreadPoolExecutor(max_workers=2) as pool: assert list(pool.map(deactivate,range(2)))==[False,False]
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count()).select_from(VersionPlan))==1
        assert db.scalar(select(func.count()).select_from(Auditoria))==2


def test_postgresql_concurrent_creation_and_exact_large_amount(pg_engine,payload):
    payload['precio_mensual'] = '999999999999.99'
    barrier = Barrier(2)
    def create(_):
        with Session(pg_engine) as db:
            barrier.wait(timeout=10)
            try: return service.create(db, PlanCreate(**payload), 100).version.precio_mensual
            except service.PlanError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(create, range(2)))
    assert set(map(str, results)) == {'999999999999.99', 'PLAN_CODE_EXISTS'}
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count()).select_from(Plan)) == 1
        assert db.scalar(select(func.count()).select_from(VersionPlan)) == 1
        assert db.scalar(select(func.count()).select_from(Auditoria)) == 1
