"""Run subscription tests using installed dependencies, with TCP disabled."""
import os
from pathlib import Path
import socket
import sys

root = Path(__file__).resolve().parents[1]
if (root / '.env').exists():
    raise SystemExit('Run this script from the isolated worktree without .env')
sys.path.insert(0, str(root))
os.chdir(root)
os.environ.update(DB_HOST='127.0.0.1', DB_PORT='1', DB_NAME='test_memory_only',
    DB_USER='test', DB_PASSWORD='test', DB_SSLMODE='disable', DB_CHANNEL_BINDING='disable',
    EMAIL_ENABLED='false', SMS_PROVIDER='console', CU17_FCM_PROJECT_ID='',
    SUBSCRIPTION_CYCLE_WORKER_ENABLED='false',
    JWT_SECRET_KEY=os.urandom(32).hex(), JWT_REFRESH_SECRET_KEY=os.urandom(32).hex())
os.environ.pop('CU34_TEST_DATABASE_URL', None)
original_connect = socket.socket.connect


def no_tcp(self, address):
    # Windows asyncio implements its self-pipe with a loopback socket pair.
    if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ('127.0.0.1','::1'):
        raise RuntimeError('Isolated tests prohibit external TCP connections')
    return original_connect(self, address)


socket.socket.connect = no_tcp
from app.core.database import engine


def no_configured_database(*args, **kwargs):
    raise RuntimeError('Isolated tests prohibit the configured PostgreSQL engine; use SQLite fixtures')


engine.dialect.connect = no_configured_database
import pytest
args = sys.argv[1:]
if not any(not arg.startswith('-') for arg in args):
    args = ['tests/cu34','tests/test_cu31_subscription_payments.py','tests/test_cu35_subscriptions.py'] + args
raise SystemExit(pytest.main(args))
