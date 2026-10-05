import hashlib
import math
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.auth.models import Usuario
from app.modules.medical_records.clinical_documents.service import audit
from app.modules.medical_records.clinical_documents.storage import storage
from app.modules.medical_records.laboratory_orders import crypto
from app.modules.medical_records.laboratory_orders.models import ExamenLaboratorio, OrdenLaboratorio
from app.modules.medical_records.laboratory_orders.schemas import (
    ExamenLaboratorioCreateRequest,
    ExamenLaboratorioResponse,
    ExamenOrdenRequest,
    ExamenOrdenResponse,
    OrdenLaboratorioCreateRequest,
    OrdenLaboratorioListResponse,
    OrdenLaboratorioResponse,
    OrdenLaboratorioPaginationResponse,
    OrdenLaboratorioDownloadResponse,
)

PERMISO_CREATE = "lab_orders:create"
PERMISO_READ = "lab_orders:read"
PERMISO_DOWNLOAD = "lab_orders:download"


class LaboratoryOrderServiceError(Exception):
    """Error de negocio con mapeo a código HTTP por el router."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _nombre_paciente(db: Session, id_paciente: Optional[int]) -> Optional[str]:
    if id_paciente is None:
        return None
    row = db.execute(
        sql_text("SELECT nombres || ' ' || apellidos FROM pacientes WHERE id_paciente = :id"),
        {"id": id_paciente},
    ).first()
    return row[0] if row and row[0] else None


def _get_examen_by_codigo(db: Session, id_clinica: int, codigo: str) -> Optional[ExamenLaboratorio]:
    return db.query(ExamenLaboratorio).filter(
        ExamenLaboratorio.id_clinica == id_clinica,
        ExamenLaboratorio.codigo == codigo.upper(),
        ExamenLaboratorio.activo == "SI",
    ).first()


def _resolve_examenes(db: Session, id_clinica: int, examenes_req: List[ExamenOrdenRequest]) -> List[dict]:
    """Resuelve códigos a objetos con nombre y valida existencia."""
    resueltos = []
    for e in examenes_req:
        examen = _get_examen_by_codigo(db, id_clinica, e.codigo)
        if not examen:
            raise LaboratoryOrderServiceError(
                422, f"Examen no encontrado en catálogo o inactivo: {e.codigo}"
            )
        resueltos.append({
            "codigo": examen.codigo,
            "nombre": examen.nombre,
            "indicaciones": e.indicaciones,
        })
    return resueltos


def _apply_role_scope(db: Session, query, current_user: Usuario, tenant_id: Optional[int], filters: dict):
    """Aplica aislamiento por tenant y alcance por rol sobre la consulta."""
    q = query

    if tenant_id is None:
        raise LaboratoryOrderServiceError(403, "No se pudo resolver el tenant del usuario")
    q = q.filter(OrdenLaboratorio.id_clinica == tenant_id)

    role_name = ""
    if current_user.id_rol:
        row = db.execute(
            sql_text("SELECT nombre FROM roles WHERE id_rol = :rid"),
            {"rid": current_user.id_rol},
        ).first()
        if row:
            role_name = row[0].upper()

    if role_name == "MEDICO":
        q = q.filter(OrdenLaboratorio.id_medico == current_user.id_usuario)

    if filters.get("estado"):
        q = q.filter(OrdenLaboratorio.estado == filters["estado"])
    if filters.get("id_paciente"):
        q = q.filter(OrdenLaboratorio.id_paciente == filters["id_paciente"])
    if filters.get("fecha_desde"):
        q = q.filter(OrdenLaboratorio.fecha_orden >= filters["fecha_desde"])
    if filters.get("fecha_hasta"):
        q = q.filter(OrdenLaboratorio.fecha_orden <= filters["fecha_hasta"])
    if filters.get("q"):
        # Búsqueda por nombre de paciente o códigos de examen (JSONB)
        q = q.filter(
            sql_text("""
                EXISTS (
                    SELECT 1 FROM jsonb_array_elements(examenes) AS elem
                    WHERE elem->>'codigo' ILIKE :q
                ) OR id_paciente IN (
                    SELECT id_paciente FROM pacientes
                    WHERE (nombres || ' ' || apellidos) ILIKE :q
                )
            """).bindparams(q=f"%{filters['q']}%")
        )

    q = q.filter(OrdenLaboratorio.estado != "ANULADA")
    return q


def _to_list_response(orden: OrdenLaboratorio, db: Session) -> OrdenLaboratorioListResponse:
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


def _to_full_response(orden: OrdenLaboratorio, db: Session) -> OrdenLaboratorioResponse:
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


def _generar_pdf_orden(orden: OrdenLaboratorio, db: Session, timestamp_firma: str) -> Tuple[bytes, str]:
    """Genera PDF de la orden firmada. Returns (pdf_bytes, hash_sha256)."""
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    story = []

    # Encabezado clínica
    clinica_row = db.execute(
        sql_text("SELECT nombre FROM clinicas WHERE id_clinica = :id"),
        {"id": orden.id_clinica},
    ).first()
    clinica_nombre = clinica_row[0] if clinica_row else "Clínica"

    story.append(Paragraph(clinica_nombre, styles["Title"]))
    story.append(Paragraph("Orden de Exámenes de Laboratorio", styles["Heading2"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black))
    story.append(Spacer(1, 12))

    # Datos paciente
    paciente_nombre = _nombre_paciente(db, orden.id_paciente) or "N/A"
    data_paciente = [
        ["Paciente:", paciente_nombre],
        ["Fecha orden:", orden.fecha_orden.strftime("%d/%m/%Y")],
        ["Médico solicitante:", f"{orden.medico.nombres} {orden.medico.apellidos}" if orden.medico else "N/A"],
    ]
    t_paciente = Table(data_paciente, colWidths=[1.5 * inch, 4.5 * inch])
    t_paciente.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_paciente)
    story.append(Spacer(1, 12))

    # Tabla exámenes
    examenes_data = [["Código", "Examen", "Indicaciones"]]
    for e in (orden.examenes or []):
        examenes_data.append([e["codigo"], e["nombre"], e.get("indicaciones", "")])
    t_examenes = Table(examenes_data, colWidths=[1 * inch, 3 * inch, 2 * inch])
    t_examenes.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0F0F0")]),
    ]))
    story.append(t_examenes)
    story.append(Spacer(1, 16))

    # Firma digital
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Firma Digital:</b>", styles["Normal"]))
    story.append(Paragraph(f"Hash HMAC-SHA256: <font face='Courier'>{orden.firma_digital}</font>", styles["Normal"]))
    story.append(Paragraph(f"Timestamp: {timestamp_firma}", styles["Normal"]))
    story.append(Paragraph(f"Médico: {orden.medico.nombres} {orden.medico.apellidos} (ID: {orden.id_medico})" if orden.medico else "Médico: N/A", styles["Normal"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Archivo SHA-256: <font face='Courier'>{orden.hash_archivo}</font>", styles["Normal"]))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    hash_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, hash_sha256


def create_draft(
    db: Session,
    data: OrdenLaboratorioCreateRequest,
    current_user: Usuario,
    tenant_id: Optional[int],
) -> OrdenLaboratorio:
    """Crea orden en estado BORRADOR."""
    target_clinica = tenant_id
    if target_clinica is None:
        raise LaboratoryOrderServiceError(400, "No se pudo resolver el tenant de la orden")

    # Validar paciente existe en tenant
    paciente = db.execute(
        sql_text("SELECT id_paciente FROM pacientes WHERE id_paciente = :id"),
        {"id": data.id_paciente},
    ).first()
    if not paciente:
        raise LaboratoryOrderServiceError(404, "Paciente no encontrado en este tenant")

    # Validar y resolver exámenes
    examenes_resueltos = _resolve_examenes(db, target_clinica, data.examenes)

    orden = OrdenLaboratorio(
        id_clinica=target_clinica,
        id_paciente=data.id_paciente,
        id_cita=data.id_cita,
        id_medico=current_user.id_usuario,
        examenes=examenes_resueltos,
        fecha_orden=date.today(),
        estado="BORRADOR",
    )
    db.add(orden)
    db.commit()
    db.refresh(orden)
    audit(db, id_clinica=target_clinica, id_usuario=current_user.id_usuario,
          tabla="ordenes_laboratorio", registro_id=orden.id_orden,
          accion="CREAR_ORDEN_LABORATORIO", descripcion=f"Orden borrador creada con {len(examenes_resueltos)} exámenes")
    return orden


def firmar_orden(
    db: Session,
    id_orden: int,
    current_user: Usuario,
    tenant_id: Optional[int],
) -> OrdenLaboratorio:
    """Firma la orden: genera PDF, firma HMAC, sube a storage, indexa en HCE (documentos_clinicos)."""
    if tenant_id is None:
        raise LaboratoryOrderServiceError(400, "No se pudo resolver el tenant")

    orden = db.query(OrdenLaboratorio).filter(
        OrdenLaboratorio.id_orden == id_orden,
        OrdenLaboratorio.id_clinica == tenant_id,
    ).first()
    if not orden:
        raise LaboratoryOrderServiceError(404, "Orden no encontrada")

    # Solo el médico creador puede firmar
    if orden.id_medico != current_user.id_usuario:
        raise LaboratoryOrderServiceError(403, "Permiso denegado: solo el médico creador puede firmar esta orden")

    if orden.estado != "BORRADOR":
        raise LaboratoryOrderServiceError(409, f"La orden ya está en estado {orden.estado} y no puede firmarse")

    # Resolver exámenes para payload canónico (ya resueltos en creación)
    examenes_para_firma = orden.examenes or []

    # Firma digital
    fecha_orden = date.today()
    firma_digital, timestamp_firma = crypto.sign_order(
        id_orden=orden.id_orden,
        id_paciente=orden.id_paciente,
        id_medico=orden.id_medico,
        examenes=examenes_para_firma,
        fecha_orden=fecha_orden,
    )

    # Generar PDF
    pdf_bytes, hash_archivo = _generar_pdf_orden(orden, db, timestamp_firma)

    # Subir a storage
    file_name = f"orden-lab-{orden.id_orden:06d}.pdf"
    object_key, _ = storage.store(file_name, pdf_bytes, "application/pdf")

    # Actualizar orden
    orden.firma_digital = firma_digital
    orden.fecha_orden = fecha_orden
    orden.estado = "FIRMADA"
    orden.archivo_url = object_key
    orden.hash_archivo = hash_archivo
    db.add(orden)

    # Indexar en HCE (documentos_clinicos) como ORDEN_LAB
    from app.modules.medical_records.clinical_documents.models import DocumentoClinico
    target_clinica = orden.id_clinica
    titulo = f"Orden de Laboratorio - {_nombre_paciente(db, orden.id_paciente) or orden.id_paciente}"
    descripcion = f"Exámenes: {', '.join([e['codigo'] for e in examenes_para_firma])}"
    metadatos = {
        "id_orden_laboratorio": orden.id_orden,
        "examenes": examenes_para_firma,
        "firma_digital": firma_digital,
        "timestamp_firma": timestamp_firma,
    }
    doc = DocumentoClinico(
        id_clinica=target_clinica,
        id_paciente=orden.id_paciente,
        id_cita=orden.id_cita,
        tipo_documento="ORDEN_LAB",
        titulo=titulo,
        descripcion=descripcion,
        archivo_url=object_key,
        hash_archivo=hash_archivo,
        firmado_por=current_user.id_usuario,
        fecha_documento=fecha_orden,
        metadatos=metadatos,
        estado="ACTIVO",
    )
    db.add(doc)

    audit(db, id_clinica=target_clinica, id_usuario=current_user.id_usuario,
          tabla="ordenes_laboratorio", registro_id=orden.id_orden,
          accion="FIRMAR_ORDEN_LABORATORIO", descripcion=f"Orden firmada y emitida con {len(examenes_para_firma)} exámenes")

    db.commit()
    db.refresh(orden)
    return orden


def list_orders(
    db: Session,
    current_user: Usuario,
    tenant_id: Optional[int],
    page: int = 1,
    page_size: int = 10,
    **filters,
) -> Tuple[List[OrdenLaboratorio], int, int]:
    query = _apply_role_scope(db, db.query(OrdenLaboratorio), current_user, tenant_id, filters)
    total = query.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    items = (
        query.order_by(OrdenLaboratorio.fecha_orden.desc(), OrdenLaboratorio.id_orden.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total, total_pages


def get_order_or_404(
    db: Session,
    id_orden: int,
    current_user: Usuario,
    tenant_id: Optional[int],
) -> Optional[OrdenLaboratorio]:
    orden = db.query(OrdenLaboratorio).filter(
        OrdenLaboratorio.id_orden == id_orden,
        OrdenLaboratorio.id_clinica == tenant_id,
    ).first()
    if not orden or orden.estado == "ANULADA":
        return None

    role_name = ""
    if current_user.id_rol:
        row = db.execute(
            sql_text("SELECT nombre FROM roles WHERE id_rol = :rid"),
            {"rid": current_user.id_rol},
        ).first()
        if row:
            role_name = row[0].upper()

    if role_name == "MEDICO" and orden.id_medico != current_user.id_usuario:
        return None

    return orden


def get_catalogo_examenes(db: Session, id_clinica: int) -> List[ExamenLaboratorioResponse]:
    examenes = db.query(ExamenLaboratorio).filter(
        ExamenLaboratorio.id_clinica == id_clinica,
        ExamenLaboratorio.activo == "SI",
    ).order_by(ExamenLaboratorio.categoria, ExamenLaboratorio.nombre).all()
    return [ExamenLaboratorioResponse.model_validate(e) for e in examenes]