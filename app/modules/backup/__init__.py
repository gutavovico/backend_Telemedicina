"""Módulo de copias de seguridad (cambio backup-copias-seguridad).

Dominio `backup` con casos `manual` (generar/listar/descargar/restaurar)
y `programado` (configuración + scheduler APScheduler en hora America/La_Paz).
"""

from app.modules.backup.router import router

__all__ = ["router"]
