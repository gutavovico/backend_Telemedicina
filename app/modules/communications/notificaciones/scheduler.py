"""Worker periódico Outbox para CU20 (APScheduler BackgroundScheduler, cada 30s)."""

from __future__ import annotations

import logging
from typing import Optional

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _APS_AVAILABLE = True
except ImportError:  # pragma: no cover
    BackgroundScheduler = None  # type: ignore
    _APS_AVAILABLE = False

from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.communications.notificaciones.service import NotificacionService

logger = logging.getLogger("notificaciones.scheduler")
_scheduler: Optional[object] = None
JOB_ID = "cu20_worker_outbox_notificaciones"


def ejecutar_lote_outbox() -> None:
    """Procesa un lote de eventos pendientes con su propia sesión DB."""
    db = SessionLocal()
    try:
        resumen = NotificacionService(db).procesar_outbox(limite=50)
        db.commit()
        if resumen.get("procesados", 0) > 0:
            logger.info("Outbox CU20 procesado: %s", resumen)
    except Exception as exc:  # noqa: BLE001 - el worker nunca debe tumbar la app
        db.rollback()
        logger.error("Error procesando outbox CU20: %s", exc)
    finally:
        db.close()


def iniciar() -> None:
    global _scheduler
    if not settings.OUTBOX_WORKER_ACTIVO:
        return
    if not _APS_AVAILABLE:
        logger.warning("APScheduler no instalado: worker outbox CU20 desactivado")
        return
    if _scheduler is not None:
        return
    try:
        intervalo = max(5, int(settings.OUTBOX_WORKER_INTERVALO_SEGUNDOS or 30))
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            ejecutar_lote_outbox,
            "interval",
            seconds=intervalo,
            id=JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        _scheduler.start()
        logger.info("Worker Outbox CU20 iniciado (cada %ss)", intervalo)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo iniciar el worker outbox CU20: %s", exc)
        _scheduler = None


def detener() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _scheduler = None


__all__ = ["iniciar", "detener", "ejecutar_lote_outbox"]
