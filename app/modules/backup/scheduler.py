"""Scheduler de copias automáticas (APScheduler, hora America/La_Paz)."""

from __future__ import annotations

import logging
from typing import Optional
from zoneinfo import ZoneInfo

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    _APS_AVAILABLE = True
except ImportError:  # pragma: no cover - sin dependencia instalada
    BackgroundScheduler = None  # type: ignore
    CronTrigger = None  # type: ignore
    _APS_AVAILABLE = False

from app.core.database import SessionLocal

try:
    LA_PAZ = ZoneInfo("America/La_Paz")
except Exception:
    from datetime import timezone, timedelta
    LA_PAZ = timezone(timedelta(hours=-4))
JOB_ID = "backup_programado"
_DIA_MAP = {"lun": "mon", "mar": "tue", "mie": "wed", "jue": "thu",
            "vie": "fri", "sab": "sat", "dom": "sun"}

logger = logging.getLogger(__name__)
scheduler: Optional[object] = None


def _ejecutar_job() -> None:
    """Dump programado con sesión propia + retención (no depende de request)."""
    from app.modules.backup import service

    db = SessionLocal()
    try:
        cfg = service.obtener_config(db)
        if not cfg.activo:
            return
        try:
            service.generar_backup(db, user=None, ip=None)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - se registra y continúa
            logger.error("backup programado falló: %s", exc)
            return
        eliminados = service.limpiar_antiguos(int(cfg.retencion_dias or 7))
        if eliminados:
            logger.info("backups antiguos eliminados: %d", eliminados)
    finally:
        db.close()


def _trigger_para(hora: str, dias: list) -> object:
    hh, mm = hora.split(":")
    days = ",".join(_DIA_MAP[d] for d in dias if d in _DIA_MAP) or "mon,tue,wed,thu,fri,sat,sun"
    return CronTrigger(hour=int(hh), minute=int(mm), day_of_week=days,
                       timezone=LA_PAZ)


def reprogramar() -> None:
    """Relee backup_config y reprograma el job en caliente."""
    from app.modules.backup import service

    if scheduler is None or not _APS_AVAILABLE:
        return
    db = SessionLocal()
    try:
        cfg = service.obtener_config(db)
        trigger = _trigger_para(cfg.hora, list(cfg.dias_semana or []))
        scheduler.add_job(_ejecutar_job, trigger=trigger, id=JOB_ID,
                          replace_existing=True)
        logger.info("backup reprogramado: %s %s activo=%s",
                    cfg.hora, cfg.dias_semana, cfg.activo)
    except Exception as exc:  # noqa: BLE001 - el scheduler no tumba la app
        logger.error("no se pudo reprogramar backup: %s", exc)
    finally:
        db.close()


def iniciar() -> None:
    """Arranca el scheduler (startup). Nunca tumba la app si falla."""
    global scheduler
    if not _APS_AVAILABLE:
        logger.warning("APScheduler no instalado: backups automáticos desactivados")
        return
    try:
        scheduler = BackgroundScheduler(timezone=str(LA_PAZ))
        scheduler.start()
        reprogramar()
    except Exception as exc:  # noqa: BLE001
        logger.error("scheduler de backup no iniciado: %s", exc)
        scheduler = None


def detener() -> None:
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass


__all__ = ["iniciar", "detener", "reprogramar"]
