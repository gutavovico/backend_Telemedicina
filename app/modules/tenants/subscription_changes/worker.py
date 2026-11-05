"""Explicit, opt-in cycle executor. No gateway charges and no import-time writes."""
import logging
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.config import settings
from app.modules.tenants.models import TenantSubscription
from app.modules.tenants.subscription_payments.service import now_utc
from .service import process_cycle

logger = logging.getLogger(__name__)
scheduler = None


def run_due(session_factory=SessionLocal, now=None):
    now = now or now_utc()
    with session_factory() as db:
        tenants = db.scalars(select(TenantSubscription.id_clinica).where(
            TenantSubscription.fecha_fin <= now, TenantSubscription.estado != 'CANCELLED')).all()
    count = 0
    for tenant in tenants:
        with session_factory() as db:
            try:
                count += process_cycle(db, tenant, now)
            except Exception:
                db.rollback()
                logger.exception('Cycle processing failed for tenant %s', tenant)
    return count


def start():
    global scheduler
    if not settings.SUBSCRIPTION_CYCLE_WORKER_ENABLED or scheduler is not None:
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(timezone='UTC')
    scheduler.add_job(run_due, 'interval', seconds=60, id='subscription-cycle',
                      max_instances=1, coalesce=True)
    scheduler.start()


def stop():
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply due actions to the explicitly configured database')
    if parser.parse_args().apply:
        print('Applied actions:', run_due())
    else:
        parser.print_help()
