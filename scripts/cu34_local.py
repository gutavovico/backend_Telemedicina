"""Explicit local-only CU34 harness. No production lifespan, backups or automatic seeding.

python -m scripts.cu34_local init
python -m scripts.cu34_local serve
Requires CU34_LOCAL_DATABASE_URL: localhost PostgreSQL and database cu34_local_* / cu34_test_*.
"""
import argparse
import os
from getpass import getpass
from secrets import token_urlsafe
from pathlib import Path
from sqlalchemy.engine import make_url


def configure():
    raw = os.environ.get('CU34_LOCAL_DATABASE_URL', '')
    if not raw: raise RuntimeError('Defina CU34_LOCAL_DATABASE_URL explícitamente; no se usa .env para elegir la base.')
    url = make_url(raw)
    if (url.get_backend_name() != 'postgresql' or url.host not in ('localhost', '127.0.0.1')
            or not (url.database or '').startswith(('cu34_local_', 'cu34_test_'))):
        raise RuntimeError('Solo se permiten bases PostgreSQL locales con prefijo cu34_local_ o cu34_test_.')
    for key, value in dict(DB_HOST=url.host, DB_PORT=str(url.port or 5432), DB_USER=url.username or 'postgres',
        DB_PASSWORD=url.password or '', DB_NAME=url.database, DB_SSLMODE='disable', DB_CHANNEL_BINDING='disable',
        JWT_SECRET_KEY=token_urlsafe(48),
        JWT_REFRESH_SECRET_KEY=token_urlsafe(48), EMAIL_ENABLED='false').items():
        os.environ[key] = value


def initialize():
    configure()
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import select
    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.modules.auth.models import Rol, Usuario
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(config, 'head')
    with SessionLocal() as db:
        role = db.scalar(select(Rol).where(Rol.nombre == 'Super Administrador', Rol.id_clinica.is_(None)))
        if role is None:
            role = Rol(nombre='Super Administrador', estado='ACTIVO', id_clinica=None)
            db.add(role); db.flush()
        if db.scalar(select(Usuario).where(Usuario.correo == 'cu34-local@example.com')) is None:
            password = os.environ.get('CU34_LOCAL_PASSWORD') or getpass('Contraseña del superadministrador local (mínimo 8 caracteres): ')
            if len(password) < 8:
                raise ValueError('La contraseña local debe tener al menos 8 caracteres.')
            db.add(Usuario(id_rol=role.id_rol, id_clinica=None, nombres='Prueba', apellidos='CU34',
                correo='cu34-local@example.com', password_hash=hash_password(password), estado='ACTIVO'))
            db.commit()
    print('Entorno local inicializado, sin planes precargados. Usuario: cu34-local@example.com. Se conserva la contraseña si la cuenta ya existía.')


def create_app():
    configure()
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from app.modules.auth.router import router as auth
    from app.modules.auth.tenant.router import router as tenant
    from app.modules.auth.planes.router import router, plan_error_handler
    from app.modules.auth.planes.service import PlanError
    app = FastAPI(title='CU34 — pruebas locales aisladas')
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:4200','http://127.0.0.1:4200'],
        allow_methods=['*'], allow_headers=['*'])
    app.include_router(auth)
    app.include_router(tenant, prefix='/api/v1')
    app.include_router(router)
    app.add_exception_handler(PlanError, plan_error_handler)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'serve'])
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.action == 'init': initialize()
    else:
        import uvicorn
        uvicorn.run(create_app(), host='127.0.0.1', port=args.port)
