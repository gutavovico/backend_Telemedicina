"""Local PostgreSQL verification only; never reads .env or permits Neon.

Set CU35_LOCAL_DATABASE_URL explicitly to a cu34_test_* database on loopback.
Commands: prepare (empty DB -> 62b0d532ee0a), migrate (020-022), test (pytest).
"""
import argparse
import os
import re
from pathlib import Path
import secrets
import socket
import sys


def configure():
    from sqlalchemy.engine import make_url
    root = Path(__file__).resolve().parents[1]
    if (root / '.env').exists():
        raise RuntimeError('Use the isolated worktree without .env')
    raw = os.environ.get('CU35_LOCAL_DATABASE_URL', '')
    if not raw:
        raise RuntimeError('Set CU35_LOCAL_DATABASE_URL explicitly; .env is never used')
    url = make_url(raw)
    if (url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1','localhost')
            or not re.fullmatch(r'cu34_test_[A-Za-z0-9_]+',url.database or '') or url.query):
        raise RuntimeError('Only explicit local PostgreSQL cu34_test_* databases without URL options are allowed')
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ.update(DB_HOST=url.host, DB_PORT=str(url.port or 5432), DB_USER=url.username or '',
        DB_PASSWORD=url.password or '', DB_NAME=url.database, DB_SSLMODE='disable', DB_CHANNEL_BINDING='disable',
        JWT_SECRET_KEY=secrets.token_urlsafe(48), JWT_REFRESH_SECRET_KEY=secrets.token_urlsafe(48),
        EMAIL_ENABLED='false', SMS_PROVIDER='console', SUBSCRIPTION_CYCLE_WORKER_ENABLED='false',
        CU34_TEST_DATABASE_URL=raw)
    original_connect = socket.socket.connect

    def local_only(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ('127.0.0.1','::1'):
            raise RuntimeError('External TCP disabled in PostgreSQL checks')
        return original_connect(self, address)

    socket.socket.connect = local_only
    return root, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','base','migrate','test'))
    args, pytest_args = parser.parse_known_args()
    root, raw = configure()
    from sqlalchemy import create_engine, text, inspect
    from alembic import command
    from alembic.config import Config
    engine = create_engine(raw)
    config = Config(str(root/'alembic.ini'))
    config.set_main_option('script_location',str(root/'alembic'))
    if args.action == 'prepare':
        with engine.connect() as conn:
            if inspect(conn).get_table_names():
                raise RuntimeError('prepare requires an empty database; preserve existing data')
        command.upgrade(config,'62b0d532ee0a')
    elif args.action in ('base','migrate'):
        with engine.connect() as conn:
            revisions = conn.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
            if revisions not in (['62b0d532ee0a'],['cu06_servicios_clinica_021'],
                                  ['merge_cu18_asistencia_022'],['cu35_integracion_022']):
                raise RuntimeError('Unexpected isolated migration base: '+str(revisions))
            counts = {table:conn.scalar(text(f'SELECT count(*) FROM {table}')) for table in
                ('planes','versiones_plan','plan_versions','tenant_subscriptions','subscription_payments')}
            print('Verified isolated base revision:',revisions[0],flush=True)
            print('Pre-migration row counts:',counts,flush=True)
        if revisions==['62b0d532ee0a']:
            with engine.connect() as conn:
                legacy=sum(conn.scalar(text(f'SELECT count(*) FROM {table}')) for table in ('plan_versions','tenant_subscriptions','subscription_payments'))
                if legacy:
                    raise RuntimeError('CU35: detener ANTES de 020 main: hay datos legacy; no autorizar su backfill por nombre. Conciliar explicitamente en copia.')
        command.upgrade(config,'cu06_servicios_clinica_021' if args.action=='base' else 'head')
    else:
        engine.dispose()
        import pytest
        if not any(not arg.startswith('-') for arg in pytest_args):
            pytest_args = ['tests/cu34','tests/test_cu35_postgres.py'] + pytest_args
        return pytest.main(pytest_args)
    with engine.connect() as conn:
        print('Alembic revision:',conn.execute(text('SELECT version_num FROM alembic_version')).scalars().all())
    engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
