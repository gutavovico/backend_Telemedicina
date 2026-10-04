"""CU27 report downloads, reusing the CU22 query service and authorization."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.database import get_db

from ..reportes import service
from ..reportes.dependencies import require_report_admin
from . import exporter
from .schemas import ExportRequest

router = APIRouter(prefix="/analytics/reportes", tags=["CU22 Reportes / CU27 Exportación"])


@router.post("/exportar")
def exportar(
    request: ExportRequest,
    db: Session = Depends(get_db),
    clinic_id: int = Depends(require_report_admin),
):
    result = service.query(db, clinic_id, request, export=True)
    payload = exporter.BUILDERS[request.formato](result, clinic_id)
    stamp = result.generado_en.strftime("%Y%m%d_%H%M%S")
    name = f"reporte_{request.reporte}_{stamp}.{request.formato}"
    return Response(
        content=payload, media_type=exporter.MIME[request.formato],
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
