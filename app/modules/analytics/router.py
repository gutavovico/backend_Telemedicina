"""Compose the CU22 and CU27 report use cases once for app.main."""

from fastapi import APIRouter

from .reportes.router import router as reportes_router
from .exportacion.router import router as exportacion_router

router = APIRouter()
router.include_router(reportes_router)
router.include_router(exportacion_router)
