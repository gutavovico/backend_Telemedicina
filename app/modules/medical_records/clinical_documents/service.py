import math
from datetime import date
from typing import List, Optional, Tuple
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.modules.auth.models import Usuario
from app.modules.medical_records.clinical_documents.dependencies import (
    get_role_name,
    user_can_read_document_type,
    user_has_permission,
)
from app.modules.medical_records.clinical_documents.models import DocumentoClinico
from app.modules.medical_records.clinical_documents.schemas import (
    DocumentoClinicoCreateRequest,
    DocumentoClinicoUpdateRequest,
)
from app.modules.medical_records.clinical_documents.storage import storage

PERMISO_SEARCH = "documents:search"
PERMISO_DOWNLOAD = "documents:download"


class DocumentServiceError(Exception):
    """Error de negocio con mapeo a código HTTP por el router."""


def _nombre_paciente(db: Session, id_paciente: Optional[int]) -> Optional[str]:
    if id_paciente is None:
        return None
    row = db.execute(
        sql_text("SELECT nombres || ' ' || apellidos FROM pacientes WHERE id_paciente = :id"),
        {"id": id_paciente},
    ).first()
    return row[0] if row and row[0] else None


def get_patient_id_by_user(db: Session, id_usuario: int) -> Optional[int]:
    """Devuelve el id_paciente del perfil propio del usuario (para rol PACIENTE)."""
    row = db.execute(
        sql_text("SELECT id_paciente FROM pacientes WHERE id_usuario = :uid"),
        {"uid": id_usuario},
    ).first()
    return row[0] if row else None


def _apply_role_scope(db: Session, query, current_user: Usuario, tenant_id: Optional[int], filters: dict):
    """Aplica aislamiento por tenant y alcance por rol sobre la consulta."""
    q = query

    # Aislamiento estricto por inquilino
    if tenant_id is not None:
        q = q.filter(DocumentoClinico.id_clinica == tenant_id)

    # Filtro por tipo de documento y verificación granular de recepción
    tipo = filters.get("tipo_documento")
    if tipo:
        # Recepción no puede leer resultados de laboratorio (matriz CU12)
        if not user_can_read_document_type(db, current_user.id_rol, tipo):
            raise DocumentServiceError(403, f"Permiso denegado para el tipo de documento {tipo}")
        q = q.filter(DocumentoClinico.tipo_documento == tipo)

    # Alcance por rol
    role_name = get_role_name(db, current_user.id_rol) or ""
    if role_name == "PACIENTE":
        patient_id = filters.get("id_paciente") or get_patient_id_by_user(db, current_user.id_usuario)
        if not patient_id:
            raise DocumentServiceError(404, "Perfil de paciente no configurado para este usuario")
        q = q.filter(DocumentoClinico.id_paciente == patient_id)
    elif role_name == "RECEPCION":
        # Recepción: puede leer recetas/órdenes/certificados, pero nunca resultados lab
        if filters.get("tipo_documento") == "RESULTADO_LAB":
            raise DocumentServiceError(403, "Permiso denegado para el tipo de documento RESULTADO_LAB")

    if filters.get("id_paciente") and role_name != "PACIENTE":
        q = q.filter(DocumentoClinico.id_paciente == filters["id_paciente"])

    if filters.get("fecha_desde"):
        q = q.filter(DocumentoClinico.fecha_documento >= filters["fecha_desde"])
    if filters.get("fecha_hasta"):
        q = q.filter(DocumentoClinico.fecha_documento <= filters["fecha_hasta"])
    if filters.get("q"):
        q = q.filter(DocumentoClinico.titulo.ilike(f"%{filters['q']}%"))

    q = q.filter(DocumentoClinico.estado == "ACTIVO")
    return q


def list_documents(
    db: Session,
    current_user: Usuario,
    tenant_id: Optional[int],
    page: int = 1,
    page_size: int = 10,
    **filters,
) -> Tuple[List[DocumentoClinico], int, int]:
    query = _apply_role_scope(db, db.query(DocumentoClinico), current_user, tenant_id, filters)
    total = query.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    items = (
        query.order_by(DocumentoClinico.fecha_documento.desc(), DocumentoClinico.id_documento.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total, total_pages


def get_document_or_404(
    db: Session,
    id_documento: int,
    current_user: Usuario,
    tenant_id: Optional[int],
) -> Optional[DocumentoClinico]:
    doc = db.query(DocumentoClinico).filter(DocumentoClinico.id_documento == id_documento).first()
    if not doc or doc.estado != "ACTIVO":
        return None
    if tenant_id is not None and doc.id_clinica != tenant_id:
        return None

    # Alcance por rol
    role_name = get_role_name(db, current_user.id_rol) or ""
    if role_name == "PACIENTE":
        patient_id = get_patient_id_by_user(db, current_user.id_usuario)
        if not patient_id or doc.id_paciente != patient_id:
            return None
    return doc


def create_document(
    db: Session,
    data: DocumentoClinicoCreateRequest,
    current_user: Usuario,
    tenant_id: Optional[int],
) -> DocumentoClinico:
    target_clinica = tenant_id
    if target_clinica is None:
        raise DocumentServiceError(400, "No se pudo resolver el tenant del documento")

    # Validar que el paciente exista dentro del tenant (si se indica)
    if data.id_paciente is not None:
        paciente = db.execute(
            sql_text("SELECT id_paciente FROM pacientes WHERE id_paciente = :id"),
            {"id": data.id_paciente},
        ).first()
        if not paciente:
            raise DocumentServiceError(404, "Paciente no encontrado")

    doc = DocumentoClinico(
        id_clinica=target_clinica,
        id_paciente=data.id_paciente,
        id_cita=data.id_cita,
        tipo_documento=data.tipo_documento,
        titulo=data.titulo.strip(),
        descripcion=data.descripcion.strip() if data.descripcion else None,
        archivo_url=data.archivo_url,
        hash_archivo=data.hash_archivo.lower(),
        firmado_por=data.firmado_por or current_user.id_usuario,
        fecha_documento=data.fecha_documento,
        metadatos=data.metadatos,
        estado="ACTIVO",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    audit(db, id_clinica=target_clinica, id_usuario=current_user.id_usuario,
          tabla="documentos_clinicos", registro_id=doc.id_documento,
          accion="CREAR_DOCUMENTO", descripcion=f"Documento {doc.tipo_documento} registrado")
    return doc


def update_document(
    db: Session,
    id_documento: int,
    data: DocumentoClinicoUpdateRequest,
    current_user: Usuario,
    tenant_id: Optional[int],
) -> Optional[DocumentoClinico]:
    doc = get_document_or_404(db, id_documento, current_user, tenant_id)
    if not doc:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            if isinstance(value, str):
                setattr(doc, field, value.strip())
            else:
                setattr(doc, field, value)
    db.commit()
    db.refresh(doc)
    return doc


def soft_delete_document(
    db: Session,
    id_documento: int,
    current_user: Usuario,
    tenant_id: Optional[int],
) -> Optional[DocumentoClinico]:
    doc = get_document_or_404(db, id_documento, current_user, tenant_id)
    if not doc:
        return None
    doc.estado = "ANULADO"
    db.commit()
    db.refresh(doc)
    return doc


def generate_download_url(
    db: Session,
    id_documento: int,
    current_user: Usuario,
    tenant_id: Optional[int],
) -> Tuple[Optional[DocumentoClinico], Optional[str], Optional[int], Optional[dict]]:
    """Genera URL de descarga firmada. Devuelve (doc, url, expira_en, info_archivo)."""
    doc = get_document_or_404(db, id_documento, current_user, tenant_id)
    if not doc:
        return None, None, None, None

    if not user_can_read_document_type(db, current_user.id_rol, doc.tipo_documento):
        raise DocumentServiceError(
            403, f"Permiso denegado para el tipo de documento {doc.tipo_documento}"
        )
    if not user_has_permission(db, current_user.id_rol, PERMISO_DOWNLOAD):
        raise DocumentServiceError(403, f"Permiso denegado. Se requiere el permiso '{PERMISO_DOWNLOAD}'.")

    file_name = doc.archivo_url.split("/")[-1]
    url, expires = storage.generate_download_url(doc.archivo_url, file_name, "application/pdf")
    return doc, url, expires, {"nombre_archivo": file_name, "content_type": "application/pdf"}


def audit(db: Session, id_clinica: int, id_usuario: int, tabla: str, registro_id: int,
          accion: str, descripcion: Optional[str] = None) -> None:
    """Registra una operación en la tabla auditoria (multitenant)."""
    db.execute(
        sql_text(
            "INSERT INTO auditoria (id_clinica, id_usuario, tabla_afectada, registro_id, accion, descripcion, direccion_ip) "
            "VALUES (:clinica, :usuario, :tabla, :registro, :accion, :desc, NULL)"
        ),
        {
            "clinica": id_clinica,
            "usuario": id_usuario,
            "tabla": tabla,
            "registro": registro_id,
            "accion": accion,
            "desc": descripcion,
        },
    )
    db.commit()


def notify_download(db: Session, doc: DocumentoClinico, accion: str) -> None:
    """Crea una notificación de tipo DOCUMENTO_DESCARGADO para el usuario destino."""
    id_usuario = None
    if doc.id_paciente:
        row = db.execute(
            sql_text("SELECT id_usuario FROM pacientes WHERE id_paciente = :id AND id_usuario IS NOT NULL"),
            {"id": doc.id_paciente},
        ).first()
        if row:
            id_usuario = row[0]

    if id_usuario is None:
        return

    db.execute(
        sql_text(
            "INSERT INTO notificaciones (id_usuario, tipo, canal, titulo, mensaje, estado) "
            "VALUES (:usuario, 'DOCUMENTO_DESCARGADO', 'EMAIL', :titulo, :mensaje, 'PENDIENTE')"
        ),
        {
            "usuario": id_usuario,
            "titulo": "Documento descargado",
            "mensaje": f"El documento {doc.titulo} ({doc.tipo_documento}) fue descargado/consultado.",
        },
    )
    db.commit()


def file_name_for(doc: DocumentoClinico) -> str:
    return doc.archivo_url.split("/")[-1] if doc.archivo_url else f"documento_{doc.id_documento}.pdf"