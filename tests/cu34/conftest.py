"""CU34 tests never use the application's configured engine or startup scheduler."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Auditoria, Clinica, Rol, Usuario, Plan, VersionPlan
from app.modules.auth.planes.router import router, plan_error_handler
from app.modules.auth.planes.service import PlanError


def migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/016_catalogo_planes_cu34.py"
    spec = importlib.util.spec_from_file_location("cu34_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def auth_tables(engine, *, previous=False):
    metadata = MetaData()
    for model in (Clinica, Rol, Usuario, Auditoria):
        model.__table__.to_metadata(metadata)
    if previous:
        audit = metadata.tables['auditoria']
        audit.c.id_clinica.nullable = False
        for constraint in list(audit.constraints):
            if constraint.name == 'ck_auditoria_global_catalogo': audit.constraints.remove(constraint)
    metadata.create_all(engine)


def seed(engine):
    with engine.begin() as conn:
        conn.execute(Clinica.__table__.insert(), [{"id_clinica": 1, "nombre": "Tenant de prueba"}])
        conn.execute(Rol.__table__.insert(), [
            {"id_rol": 90, "id_clinica": None, "nombre": "Super Administrador", "estado": "ACTIVO"},
            {"id_rol": 1, "id_clinica": 1, "nombre": "ADMIN", "estado": "ACTIVO"},
            {"id_rol": 2, "id_clinica": 1, "nombre": "SUPERADMIN", "estado": "ACTIVO"},
            {"id_rol": 3, "id_clinica": None, "nombre": "SUPERVISOR", "estado": "ACTIVO"},
        ])
        conn.execute(Usuario.__table__.insert(), [dict(id_usuario=i, id_clinica=clinic, id_rol=role,
            nombres="Prueba", apellidos="CU34", correo=f"cu34-{i}@example.test", password_hash="not-a-login", estado="ACTIVO")
            for i, clinic, role in [(100,None,90),(101,1,1),(102,1,2),(103,None,3)]])


@pytest.fixture
def engine():
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(db, 'connect')
    def foreign_keys(connection, _): connection.execute('PRAGMA foreign_keys=ON')
    auth_tables(db)
    Plan.__table__.create(db)
    VersionPlan.__table__.create(db)
    seed(db)
    yield db
    db.dispose()


@pytest.fixture
def client(engine):
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(PlanError, plan_error_handler)
    sessions = sessionmaker(engine)
    def db_override():
        with sessions() as db: yield db
    def actor(db: Session = Depends(get_db), x_test_actor: int = Header(100)):
        if x_test_actor == 0: raise HTTPException(401, "No autenticado")
        return db.scalar(select(Usuario).where(Usuario.id_usuario == x_test_actor))
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = actor
    with TestClient(app, raise_server_exceptions=False) as result: yield result


@pytest.fixture
def pg_engine():
    value = os.environ.get('CU34_TEST_DATABASE_URL')
    if not value: pytest.skip('Set CU34_TEST_DATABASE_URL to an isolated local PostgreSQL database')
    url = make_url(value)
    if url.host not in ('localhost', '127.0.0.1') or not (url.database or '').startswith('cu34_test_') or url.query:
        pytest.fail('CU34 tests refuse nonlocal databases or names without cu34_test_ prefix')
    schema = 'cu34_' + uuid4().hex
    root = create_engine(url)
    with root.begin() as conn: conn.exec_driver_sql(f'CREATE SCHEMA {schema}')
    db = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    auth_tables(db, previous=True)
    module = migration()
    with db.begin() as conn:
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
    seed(db)
    yield db
    db.dispose()
    with root.begin() as conn: conn.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
    root.dispose()


@pytest.fixture
def payload():
    return dict(codigo='TEST', nombre='Plan de prueba', descripcion='Solo pruebas aisladas',
        precio_mensual='1234.56', moneda='BOB', ciclo='MENSUAL', servicios_incluidos=['AGENDA_TELECONSULTA'],
        limite_medicos=3, limite_sedes=0, limite_consultas=None, tarifas_excedentes=[
            dict(recurso='MEDICOS', unidad='MEDICO_CICLO_MENSUAL', precio='12.10')], demora_pago_dias=0)
