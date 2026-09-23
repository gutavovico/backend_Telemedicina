from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.clinical_documents import service
from app.modules.medical_records.clinical_documents.dependencies import (
    PERMISO_DOWNLOAD,
    PERMISO_SEARCH,
    require_document_permission,
    require_roles_raw,
)
from app.modules.medical_records.clinical_documents.models import DocumentoClinico
from app.modules.medical_records.clinical_documents.schemas import (
    DocumentoClinicoCreateRequest,
    DocumentoClinicoPaginationResponse,
    DocumentoClinicoResponse,
    DocumentoClinicoUpdateRequest,
    DocumentoDownloadResponse,
    DocumentoResumenResponse,
)
from app.modules.medical_records.clinical_documents.storage import storage

router = APIRouter(prefix="/api/v1/documentos", tags=["Documentos Clínicos (CU12)"])

# Ruta de contratos: GET /api/v1/pacientes/{id_paciente}/documentos (CU12)
pacientes_doc_router = APIRouter(prefix="/api/v1/pacientes", tags=["Documentos Clínicos (CU12)"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.DocumentServiceError):
        return HTTPException(status_code=exc.args[0], detail=exc.args[1] if len(exc.args) > 1 else "Error")
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno del servidor")


def _to_summary(doc: DocumentoClinico, db: Session) -> DocumentoResumenResponse:
    return DocumentoResumenResponse(
        id_documento=doc.id_documento,
        id_clinica=doc.id_clinica,
        id_paciente=doc.id_paciente,
        tipo_documento=doc.tipo_documento,
        titulo=doc.titulo,
        fecha_documento=doc.fecha_documento,
        estado=doc.estado,
        created_at=doc.created_at,
        paciente_nombre=service._nombre_paciente(db, doc.id_paciente),
    )


@router.get(
    "",
    response_model=DocumentoClinicoPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar documentos clínicos del tenant",
    description="Lista paginada de documentos clínicos con filtros y alcance por rol.",
)
def list_documents_endpoint(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(10, ge=1, le=100, description="Cantidad por página"),
    tipo_documento: Optional[str] = Query(None, description="Filtro por tipo de documento"),
    fecha_desde: Optional[date] = Query(None, description="Filtro rango inicial"),
    fecha_hasta: Optional[date] = Query(None, description="Filtro rango final"),
    id_paciente: Optional[int] = Query(None, description="Documentos de un paciente"),
    q: Optional[str] = Query(None, description="Búsqueda por título"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_document_permission(PERMISO_SEARCH)),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    try:
        items, total, total_pages = service.list_documents(
            db,
            current_user,
            tenant_id,
            page=page,
            page_size=page_size,
            tipo_documento=tipo_documento.upper() if tipo_documento else None,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_paciente=id_paciente,
            q=q,
        )
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from exc

    return DocumentoClinicoPaginationResponse(
        items=[_to_summary(doc, db) for doc in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/me",
    response_model=DocumentoClinicoPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar documentos del paciente autenticado",
    description="Solo rol PACIENTE. Devuelve exclusivamente sus propios documentos clínicos.",
)
def list_my_documents_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    tipo_documento: Optional[str] = Query(None),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles_raw(["PACIENTE"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    patient_id = service.get_patient_id_by_user(db, current_user.id_usuario)
    if not patient_id:
        raise HTTPException(status_code=404, detail="Perfil de paciente no configurado para este usuario")

    try:
        items, total, total_pages = service.list_documents(
            db,
            current_user,
            tenant_id,
            page=page,
            page_size=page_size,
            tipo_documento=tipo_documento.upper() if tipo_documento else None,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_paciente=patient_id,
            q=q,
        )
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from exc

    return DocumentoClinicoPaginationResponse(
        items=[_to_summary(doc, db) for doc in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@pacientes_doc_router.get(
    "/{id_paciente}/documentos",
    response_model=DocumentoClinicoPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar documentos de un paciente del tenant",
    description="Roles ADMIN, MEDICO y RECEPCION (ver matriz de permisos CU12).",
)
def list_patient_documents_endpoint(
    id_paciente: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    tipo_documento: Optional[str] = Query(None),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles_raw(["ADMIN", "MEDICO", "RECEPCION"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    paciente = db.execute(
        sql_text("SELECT id_paciente FROM pacientes WHERE id_paciente = :id"),
        {"id": id_paciente},
    ).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    try:
        items, total, total_pages = service.list_documents(
            db,
            current_user,
            tenant_id,
            page=page,
            page_size=page_size,
            tipo_documento=tipo_documento.upper() if tipo_documento else None,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_paciente=id_paciente,
            q=q,
        )
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from exc

    return DocumentoClinicoPaginationResponse(
        items=[_to_summary(doc, db) for doc in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{id_documento}",
    response_model=DocumentoClinicoResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle de un documento clínico",
    description="Valida pertenencia al tenant y permiso granular del tipo de documento.",
)
def get_document_detail_endpoint(
    id_documento: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    doc = service.get_document_or_404(db, id_documento, current_user, tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    from app.modules.medical_records.clinical_documents.dependencies import user_can_read_document_type
    if not user_can_read_document_type(db, current_user.id_rol, doc.tipo_documento):
        raise HTTPException(status_code=403, detail=f"Permiso denegado para el tipo de documento {doc.tipo_documento}")

    resp = DocumentoClinicoResponse.model_validate(doc)
    resp.tenant_id = doc.id_clinica
    resp.paciente_nombre = service._nombre_paciente(db, doc.id_paciente)
    if doc.firmante:
        resp.firmante_nombre = f"{doc.firmante.nombres} {doc.firmante.apellidos}"
    return resp


@router.get(
    "/{id_documento}/download",
    response_model=DocumentoDownloadResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar URL de descarga de un documento",
    description="Genera url_firmada temporal (≤900 s), registra auditoría y notifica al usuario destino.",
)
def download_document_endpoint(
    id_documento: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_document_permission(PERMISO_DOWNLOAD)),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    try:
        doc, url, expires, info = service.generate_download_url(db, id_documento, current_user, tenant_id)
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from exc

    if not doc or not url:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    # Auditoría y notificación (CU12 / RN-CU12-07)
    service.audit(db, id_clinica=doc.id_clinica, id_usuario=current_user.id_usuario,
                  tabla="documentos_clinicos", registro_id=doc.id_documento,
                  accion="DESCARGAR_DOCUMENTO", descripcion=f"Descarga de {doc.tipo_documento}: {doc.titulo}")
    service.notify_download(db, doc, "DOCUMENTO_DESCARGADO")

    return DocumentoDownloadResponse(
        id_documento=doc.id_documento,
        url_firmada=url,
        expira_en=expires,
        nombre_archivo=info["nombre_archivo"],
        content_type=info["content_type"],
    )


@router.get(
    "/file/{archivo_path:path}",
    status_code=status.HTTP_200_OK,
    summary="Servir archivo PDF (backend local)",
    description="Endpoint solo para el backend local. Permite descargar el archivo del storage local autenticado.",
    include_in_schema=False,
)
def serve_local_file_endpoint(
    archivo_path: str,
    nombre: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_document_permission(PERMISO_DOWNLOAD)),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    content = storage.read(archivo_path)
    if not content:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nombre or "documento.pdf"}"'})


@router.post(
    "",
    response_model=DocumentoClinicoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un documento clínico",
    description="Permite a ADMIN/MEDICO indexar un documento clínico firmado.",
)
def create_document_endpoint(
    data: DocumentoClinicoCreateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles_raw(["ADMIN", "MEDICO"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    try:
        doc = service.create_document(db, data, current_user, tenant_id)
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from exc
    resp = DocumentoClinicoResponse.model_validate(doc)
    resp.tenant_id = doc.id_clinica
    resp.paciente_nombre = service._nombre_paciente(db, doc.id_paciente)
    return resp


@router.put(
    "/{id_documento}",
    response_model=DocumentoClinicoResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar metadata de un documento",
    description="Permite a ADMIN/MEDICO actualizar metadatos de un documento clínico.",
)
def update_document_endpoint(
    id_documento: int,
    data: DocumentoClinicoUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles_raw(["ADMIN", "MEDICO"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    doc = service.update_document(db, id_documento, data, current_user, tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    resp = DocumentoClinicoResponse.model_validate(doc)
    resp.tenant_id = doc.id_clinica
    resp.paciente_nombre = service._nombre_paciente(db, doc.id_paciente)
    return resp


@router.delete(
    "/{id_documento}",
    status_code=status.HTTP_200_OK,
    summary="Anular (baja lógica) un documento clínico",
    description="Solo ADMIN. Cambia el estado a 'ANULADO' (baja lógica).",
)
def delete_document_endpoint(
    id_documento: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles_raw(["ADMIN"])),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    doc = service.soft_delete_document(db, id_documento, current_user, tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return {"detail": "Documento anulado correctamente", "id_documento": id_documento, "estado": "ANULADO"}