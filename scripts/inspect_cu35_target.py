"""Read-only Neon schema inspection. No app settings, migration or .env mutation."""
import argparse
from getpass import getpass
import json
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,help='Optional existing connection file; values are never printed')
    args=parser.parse_args()
    if args.env_file:
        from dotenv import dotenv_values
        v=dotenv_values(args.env_file)
        url=URL.create('postgresql+psycopg2',username=v.get('DB_USER'),password=v.get('DB_PASSWORD'),
            host=v.get('DB_HOST'),port=int(v.get('DB_PORT') or 5432),database=v.get('DB_NAME'))
    else:
        url=make_url(getpass('Connection URL from the selected Neon branch (hidden): '))
    if not (url.host or '').endswith('.neon.tech') or set(url.query)-{'sslmode','channel_binding'}:
        raise SystemExit('Refusing unverified/non-Neon endpoint or URL options; use a plain Neon connection URL')
    url=url.set(query={})
    engine=create_engine(url,connect_args={'sslmode':'require','connect_timeout':10,
        'options':'-c default_transaction_read_only=on'})
    try:
        with engine.connect() as c:
            if c.scalar(text('SHOW transaction_read_only'))!='on':
                raise RuntimeError('Server did not enforce read-only mode')
            c.exec_driver_sql("SET LOCAL statement_timeout='10s'")
            revision=c.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
            identity=c.execute(text("SELECT current_setting('neon.project_id',true), current_setting('neon.branch_id',true), current_setting('neon.endpoint_id',true)")).one()
            columns=c.execute(text("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('tenant_subscriptions','subscription_payments') AND column_name IN ('id_version_plan','version_plan_id','billing_anchor_day','purpose') ORDER BY table_name,column_name")).all()
            counts={t:c.scalar(text(f'SELECT count(*) FROM {t}')) for t in
                ('plan_versions','versiones_plan','tenant_subscriptions','subscription_payments')}
            print(json.dumps({'read_only':True,'neon_identifiers':dict(zip(('project_id','branch_id','endpoint_id'),identity)),
                'branch_label':'production/test label not verified by management API',
                'revision':revision,'columns':[list(row) for row in columns],'row_counts':counts},indent=2))
            c.rollback()
    except SQLAlchemyError as exc:
        detail=str(exc.orig)
        for value in (url.password,url.username,url.host,url.database):
            if value: detail=detail.replace(str(value),'[withheld]')
        print('Inspection blocked:',type(exc.orig).__name__,detail[:700])
        return 1
    finally:
        engine.dispose()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
