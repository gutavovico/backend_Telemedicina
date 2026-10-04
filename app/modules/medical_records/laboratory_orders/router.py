from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.laboratory_orders import service
from app.modules.medical_records.laboratory_orders.dependencies import (
    PERMISO_CREATE,
    PERMISO_DOWNLOAD,
    PERMISO_READ,
    require_lab_order_permission,
    require_roles_lab_order,
    user_can_access_lab_order,
)
from app.modules.medical_records.laboratory_orders.schemas import (
    ExamenLaboratorioResponse,
    OrdenLaboratorioCreateRequest,
    OrdenLaboratorioFirmarRequest,
    OrdenLaboratorioListResponse,
    OrdenLaboratorioPaginationResponse,
    OrdenLaboratorioResponse,
    OrdenLaboratorioDownloadResponse,
)
from app.modules.medical_records.clinical_documents.service import generate_download_url
from app.modules.medical_records.clinical_documents.models import DocumentoClinico

router = APIRouter(prefix="/api/v1/ordenes-laboratorio", tags=["Órdenes de Laboratorio (CU10)"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.LaboratoryOrderServiceError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno del servidor")


def _to_list_response(orden, db: Session) -> OrdenLaboratorioListResponse:
    from app.modules.medical_records.laboratory_orders.service import _nombre_paciente
    examenes_codigos = [e["codigo"] for e in (orden.examenes or [])]
    return OrdenLaboratorioListResponse(
        id_orden=orden.id_orden,
        id_clinica=orden.id_clinica,
        id_paciente=orden.id_paciente,
        paciente_nombre=_nombre_paciente(db, orden.id_paciente),
        examenes_codigos=examenes_codigos,
        estado=orden.estado,
        fecha_orden=orden.fecha_orden,
        created_at=orden.created_at,
    )


@router.get(
    "/examenes",
    response_model=list[ExamenLaboratorioResponse],
    status_code=status.HTTP_200_OK,
    summary="Catálogo de exámenes activos del tenant",
    description="Devuelve el catálogo de exámenes de laboratorio (activo=SI) para selección en formulario.",
)
def list_examenes_catalogo(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_lab_order_permission(PERMISO_READ)),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return service.get_catalogo_examenes(db, tenant_id)


@router.post(
    "",
    response_model=OrdenLaboratorioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear orden de laboratorio en borrador",
    description="Crea una orden en estado BORRADOR con los exámenes seleccionados. Solo MEDICO.",
)
def create_orden(
    data: OrdenLaboratorioCreateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles_lab_order(["MEDICO"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    try:
        orden = service.create_draft(db, data, current_user, tenant_id)
    except service.LaboratoryOrderServiceError as exc:
        raise _http_error(exc) from exc
    return _to_full_response(orden, db)


@router.post(
    "/{id_orden}/firmar",
    response_model=OrdenLaboratorioResponse,
    status_code=status.HTTP_200_OK,
    summary="Firmar y emitir orden de laboratorio",
    description="Firma digitalmente la orden (HMAC-SHA256), genera PDF, indexa en HCE como ORDEN_LAB. Solo el médico creador.",
)
def firmar_orden(
    id_orden: int,
    data: OrdenLaboratorioFirmarRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles_lab_order(["MEDICO"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    try:
        orden = service.firmar_orden(db, id_orden, current_user, tenant_id)
    except service.LaboratoryOrderServiceError as exc:
        raise _http_error(exc) from exc
    return _to_full_response(orden, db)


@router.get(
    "",
    response_model=OrdenLaboratorioPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar órdenes de laboratorio del tenant",
    description="Lista paginada con filtros y alcance por rol (MEDICO ve solo propias).",
)
def list_ordenes(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    estado: Optional[str] = Query(None, description="BORRADOR, FIRMADA, ANULADA"),
    id_paciente: Optional[int] = Query(None),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_lab_order_permission(PERMISO_READ)),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    try:
        items, total, total_pages = service.list_orders(
            db, current_user, tenant_id,
            page=page, page_size=page_size,
            estado=estado, id_paciente=id_paciente,
            fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, q=q,
        )
    except service.LaboratoryOrderServiceError as exc:
        raise _http_error(exc) from exc

    return OrdenLaboratorioPaginationResponse(
        items=[_to_list_response(o, db) for o in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{id_orden}",
    response_model=OrdenLaboratorioResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle de una orden",
    description="Valida pertenencia al tenant y acceso por rol (MEDICO solo propias).",
)
def get_orden(
    id_orden: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    orden = service.get_order_or_404(db, id_orden, current_user, tenant_id)
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    if not user_can_access_lab_order(db, current_user, orden):
        raise HTTPException(status_code=403, detail="Permiso denegado para esta orden")

    return _to_full_response(orden, db)


@router.get(
    "/{id_orden}/download",
    response_model=OrdenLaboratorioDownloadResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar URL de descarga del PDF de la orden",
    description="Genera url_firmada temporal (≤900s), registra auditoría. Requiere orden FIRMADA.",
)
def download_orden(
    id_orden: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_lab_order_permission(PERMISO_DOWNLOAD)),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    orden = service.get_order_or_404(db, id_orden, current_user, tenant_id)
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    if not user_can_access_lab_order(db, current_user, orden):
        raise HTTPException(status_code=403, detail="Permiso denegado para esta orden")

    if orden.estado != "FIRMADA" or not orden.archivo_url:
        raise HTTPException(status_code=404, detail="La orden no tiene PDF generado (no firmada)")

    # Buscar el documento_clinico asociado para reusar download de CU12
    doc = db.query(DocumentoClinico).filter(
        DocumentoClinico.tipo_documento == "ORDEN_LAB",
        DocumentoClinico.metadatos.op("->>")("id_orden_laboratorio") == str(id_orden),
        DocumentoClinico.id_clinica == tenant_id,
        DocumentoClinico.estado == "ACTIVO",
    ).first()

    if not doc:
        # Fallback: generar URL directa desde storage (sin auditoría CU12)
        from app.modules.medical_records.clinical_documents.storage import storage
        file_name = orden.archivo_url.split("/")[-1]
        url, expires = storage.generate_download_url(orden.archivo_url, file_name, "application/pdf")
        return OrdenLaboratorioDownloadResponse(
            id_orden=orden.id_orden,
            url_firmada=url,
            expira_en=expires,
            nombre_archivo=file_name,
            content_type="application/pdf",
        )

    # Reusar endpoint de descarga de CU12 (auditoría + notificación)
    try:
        doc_dl, url, expires, info = generate_download_url(db, doc.id_documento, current_user, tenant_id)
    except service.LaboratoryOrderServiceError as exc:
        raise _http_error(exc) from exc

    if not url:
        raise HTTPException(status_code=404, detail="No se pudo generar URL de descarga")

    return OrdenLaboratorioDownloadResponse(
        id_orden=orden.id_orden,
        url_firmada=url,
        expira_en=expires,
        nombre_archivo=info["nombre_archivo"],
        content_type=info["content_type"],
    )


def _to_full_response(orden, db: Session) -> OrdenLaboratorioResponse:
    from app.modules.medical_records.laboratory_orders.service import _nombre_paciente
    from app.modules.medical_records.laboratory_orders.schemas import ExamenOrdenResponse
    examenes_resp = [
        ExamenOrdenResponse(codigo=e["codigo"], nombre=e["nombre"], indicaciones=e.get("indicaciones"))
        for e in (orden.examenes or [])
    ]
    return OrdenLaboratorioResponse(
        id_orden=orden.id_orden,
        id_clinica=orden.id_clinica,
        id_paciente=orden.id_paciente,
        id_cita=orden.id_cita,
        id_medico=orden.id_medico,
        examenes=examenes_resp,
        firma_digital=orden.firma_digital,
        fecha_orden=orden.fecha_orden,
        estado=orden.estado,
        archivo_url=orden.archivo_url,
        hash_archivo=orden.hash_archivo,
        created_at=orden.created_at,
        updated_at=orden.updated_at,
        paciente_nombre=_nombre_paciente(db, orden.id_paciente),
        medico_nombre=f"{orden.medico.nombres} {orden.medico.apellidos}" if orden.medico else None,
    )