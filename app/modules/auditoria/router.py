from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies.tenant import get_current_tenant_optional, is_super_admin
from app.modules.auth.dependencies import require_roles
from app.modules.auth.models import Clinica, Usuario
from app.modules.auditoria import service
from app.modules.auditoria.schemas import AuditLogEntry, AuditLogListResponse

router = APIRouter(prefix="/api/v1/audit-log", tags=["Bitácora de Auditoría (CU21)"])


def _resolve_audit_tenant_id(current_user: Usuario, tenant: Optional[Clinica]) -> Optional[int]:
    """Helper to resolve tenant_id for audit logs: None for global Super Admin, int for tenant."""
    if is_super_admin(current_user):
        return tenant.id_clinica if tenant else None
    if tenant:
        return tenant.id_clinica
    return current_user.id_clinica


@router.get(
    "",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar bitácora de auditoría con filtros y paginación (CU21)",
    description="Permite a administradores y auditores consultar el historial de operaciones del tenant autenticado o global para Super Admin."
)
def list_audit_logs(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(20, ge=1, le=100, description="Registros por página"),
    fecha_inicio: Optional[datetime] = Query(None, description="Fecha de inicio (ISO 8601)"),
    fecha_fin: Optional[datetime] = Query(None, description="Fecha de fin (ISO 8601)"),
    id_usuario: Optional[int] = Query(None, description="Filtrar por ID de usuario"),
    accion: Optional[str] = Query(None, description="Filtrar por tipo de acción (INSERT, UPDATE, DELETE, etc.)"),
    tabla_afectada: Optional[str] = Query(None, description="Filtrar por tabla afectada"),
    registro_id: Optional[int] = Query(None, description="Filtrar por ID de registro"),
    busqueda: Optional[str] = Query(None, description="Búsqueda global por texto"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN", "ADMINISTRADOR", "ADMINISTRACION", "AUDITOR"])),
    tenant: Optional[Clinica] = Depends(get_current_tenant_optional),
):
    tenant_id = _resolve_audit_tenant_id(current_user, tenant)
    return service.get_audit_logs(
        db=db,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        id_usuario=id_usuario,
        accion=accion,
        tabla_afectada=tabla_afectada,
        registro_id=registro_id,
        busqueda=busqueda
    )


@router.get(
    "/export/pdf",
    status_code=status.HTTP_200_OK,
    summary="Exportar bitácora en formato PDF (CU21)",
    description="Descarga el historial de auditoría filtrado en un archivo PDF formal."
)
def export_audit_pdf(
    fecha_inicio: Optional[datetime] = Query(None),
    fecha_fin: Optional[datetime] = Query(None),
    id_usuario: Optional[int] = Query(None),
    accion: Optional[str] = Query(None),
    tabla_afectada: Optional[str] = Query(None),
    registro_id: Optional[int] = Query(None),
    busqueda: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN", "ADMINISTRADOR", "ADMINISTRACION", "AUDITOR"])),
    tenant: Optional[Clinica] = Depends(get_current_tenant_optional),
):
    tenant_id = _resolve_audit_tenant_id(current_user, tenant)
    pdf_stream = service.export_audit_logs_pdf(
        db=db,
        tenant_id=tenant_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        id_usuario=id_usuario,
        accion=accion,
        tabla_afectada=tabla_afectada,
        registro_id=registro_id,
        busqueda=busqueda
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bitacora_auditoria_{timestamp}.pdf"

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get(
    "/export/excel",
    status_code=status.HTTP_200_OK,
    summary="Exportar bitácora en formato Excel (CU21)",
    description="Descarga el historial de auditoría filtrado en una hoja de cálculo Excel (.xlsx)."
)
def export_audit_excel(
    fecha_inicio: Optional[datetime] = Query(None),
    fecha_fin: Optional[datetime] = Query(None),
    id_usuario: Optional[int] = Query(None),
    accion: Optional[str] = Query(None),
    tabla_afectada: Optional[str] = Query(None),
    registro_id: Optional[int] = Query(None),
    busqueda: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN", "ADMINISTRADOR", "ADMINISTRACION", "AUDITOR"])),
    tenant: Optional[Clinica] = Depends(get_current_tenant_optional),
):
    tenant_id = _resolve_audit_tenant_id(current_user, tenant)
    excel_stream = service.export_audit_logs_excel(
        db=db,
        tenant_id=tenant_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        id_usuario=id_usuario,
        accion=accion,
        tabla_afectada=tabla_afectada,
        registro_id=registro_id,
        busqueda=busqueda
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bitacora_auditoria_{timestamp}.xlsx"

    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get(
    "/{id_auditoria}",
    response_model=AuditLogEntry,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle de un registro de auditoría (CU21)"
)
def get_audit_log_detail(
    id_auditoria: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["ADMIN", "ADMINISTRADOR", "ADMINISTRACION", "AUDITOR"])),
    tenant: Optional[Clinica] = Depends(get_current_tenant_optional),
):
    tenant_id = _resolve_audit_tenant_id(current_user, tenant)
    entry = service.get_audit_log_by_id(db=db, id_auditoria=id_auditoria, tenant_id=tenant_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro de auditoría no encontrado o no pertenece a este tenant"
        )
    return entry

