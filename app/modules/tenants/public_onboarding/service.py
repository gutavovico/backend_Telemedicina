import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.core.security import decrypt_temporary_credential
from app.modules.auth.models import Clinica, Plan, VersionPlan
from app.modules.tenants.models import (
    TenantRequest,
    TenantRequestTrackingAudit,
)
from app.modules.tenants.public_onboarding.schemas import (
    TenantRequestCreateResponse,
    TenantRequestTrackingResponse,
)

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

EXTENSION_BY_MIME = {
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
}

# Límite del portal público: por IP y por correo de contacto.
RATE_LIMIT_WINDOW_SECONDS = 900
RATE_LIMIT_PER_IP = 20
RATE_LIMIT_PER_EMAIL = 5
_rate_attempts: dict[str, deque] = defaultdict(deque)
_tracking_rate_attempts: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()
TRACKING_RATE_LIMIT_WINDOW_SECONDS = 900
TRACKING_RATE_LIMIT_PER_IP = 30
TRACKING_RATE_LIMIT_PER_CODE = 10


def _rate_limit_keys(client_ip: Optional[str], correo: str) -> List[str]:
    keys = []
    if client_ip:
        keys.append(f"ip:{client_ip}")
    normalized_email = (correo or "").strip().lower()
    if normalized_email:
        keys.append(f"email:{normalized_email}")
    return keys


def _check_rate_limit(client_ip: Optional[str], correo: str) -> None:
    ahora = time.monotonic()
    keys = _rate_limit_keys(client_ip, correo)
    with _rate_lock:
        for key in keys:
            intentos = _rate_attempts[key]
            while intentos and ahora - intentos[0] > RATE_LIMIT_WINDOW_SECONDS:
                intentos.popleft()
            limite = RATE_LIMIT_PER_IP if key.startswith("ip:") else RATE_LIMIT_PER_EMAIL
            if len(intentos) >= limite:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        "Se superó el límite de solicitudes. "
                        "Intente nuevamente más tarde."
                    ),
                )
        for key in keys:
            _rate_attempts[key].append(ahora)


def reset_public_rate_limits() -> None:
    """Utilidad para pruebas: limpia las ventanas de los limitadores en memoria."""
    with _rate_lock:
        _rate_attempts.clear()
        _tracking_rate_attempts.clear()


def _tracking_code_hash(tracking_code: str) -> str:
    return hashlib.sha256(tracking_code.strip().encode("utf-8")).hexdigest()


def _check_tracking_rate_limit(client_ip: Optional[str], tracking_code: str) -> None:
    ahora = time.monotonic()
    keys = [f"code:{_tracking_code_hash(tracking_code)}"]
    if client_ip:
        keys.append(f"tracking-ip:{client_ip}")
    with _rate_lock:
        for key in keys:
            intentos = _tracking_rate_attempts[key]
            while intentos and ahora - intentos[0] > TRACKING_RATE_LIMIT_WINDOW_SECONDS:
                intentos.popleft()
            limite = (
                TRACKING_RATE_LIMIT_PER_CODE if key.startswith("code:")
                else TRACKING_RATE_LIMIT_PER_IP
            )
            if len(intentos) >= limite:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Se superó el límite de consultas. Intente nuevamente más tarde.",
                )
        for key in keys:
            _tracking_rate_attempts[key].append(ahora)


def _audit_tracking(
    db: Session,
    tracking_code: str,
    accion: str,
    resultado: str,
    id_request: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    db.add(TenantRequestTrackingAudit(
        id_request=id_request,
        tracking_code_hash=_tracking_code_hash(tracking_code),
        accion=accion,
        resultado=resultado,
        direccion_ip=client_ip,
        user_agent=(user_agent or "")[:512] or None,
    ))
    db.commit()


def normalize_nit(nit: str) -> str:
    """Elimina guiones, espacios y convierte a mayúsculas para unicidad."""
    return "".join(c for c in nit.upper() if c.isalnum())


def validate_email_format(email: str, field_name: str) -> None:
    if not EMAIL_REGEX.match(email.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Formato de correo no válido en '{field_name}'.",
        )


def _sniff_mime(content: bytes) -> Optional[str]:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def _validate_document(doc: UploadFile):
    """Valida extensión, MIME declarado y firma real del archivo."""
    if not doc.filename:
        return None

    clean_filename = os.path.basename(doc.filename)
    _, ext = os.path.splitext(clean_filename)
    ext = ext.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Extensión no permitida para el archivo '{clean_filename}'. "
                "Solo se admiten PDF, JPG y PNG."
            ),
        )

    content = doc.file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"El archivo '{clean_filename}' supera el tamaño máximo "
                "permitido de 10 MB."
            ),
        )

    declared_mime = (doc.content_type or "").split(";")[0].strip().lower()
    if declared_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tipo de archivo no permitido para '{clean_filename}'.",
        )

    real_mime = _sniff_mime(content)
    if real_mime is None or real_mime != declared_mime:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"El contenido del archivo '{clean_filename}' no coincide con "
                "su extensión o tipo declarado."
            ),
        )

    if ext not in EXTENSION_BY_MIME.get(real_mime, set()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La extensión de '{clean_filename}' no corresponde al tipo "
                "real del archivo."
            ),
        )

    return {
        "original_name": clean_filename,
        "ext": ext,
        "mime_type": real_mime,
        "content": content,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }


def create_public_tenant_request(
    db: Session,
    nombre: str,
    razon_social: Optional[str],
    nit: str,
    correo: str,
    telefono: Optional[str],
    direccion: Optional[str],
    responsable_nombre: str,
    responsable_correo: str,
    responsable_telefono: Optional[str],
    plan_version_id: Optional[int],
    documentos: List[UploadFile],
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    upload_dir: str = "uploads/tenant_documents",
) -> TenantRequestCreateResponse:
    # 0. Límite de solicitudes (por IP y por correo de contacto).
    _check_rate_limit(client_ip, correo)

    # 1. Validaciones básicas de campos requeridos
    if not nombre or not nombre.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El nombre de la institución es requerido.")
    if not nit or not nit.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El NIT es requerido.")
    if not correo or not correo.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El correo institucional es requerido.")
    if not responsable_nombre or not responsable_nombre.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El nombre del responsable es requerido.")
    if not responsable_correo or not responsable_correo.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El correo del responsable es requerido.")

    validate_email_format(correo, "correo")
    validate_email_format(responsable_correo, "responsable_correo")

    # 2. Normalización de NIT y verificación de duplicados
    norm_nit = normalize_nit(nit)
    if not norm_nit:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El NIT proporcionado no es válido.")

    pending_req = db.query(TenantRequest).filter(TenantRequest.status == "PENDING").all()
    for req in pending_req:
        if normalize_nit(req.nit) == norm_nit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una solicitud pendiente o entidad activa con este NIT.",
            )

    existing_clinicas = db.query(Clinica).all()
    for clinica in existing_clinicas:
        if clinica.nit and normalize_nit(clinica.nit) == norm_nit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una solicitud pendiente o entidad activa con este NIT.",
            )

    # 3. Validación del plan canónico CU34 si se especificó
    if plan_version_id:
        plan = (
            db.query(VersionPlan)
            .join(Plan, Plan.id == VersionPlan.plan_id)
            .filter(
                VersionPlan.id == plan_version_id,
                Plan.activo.is_(True),
                VersionPlan.numero == Plan.version_actual,
            )
            .first()
        )
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El plan seleccionado '{plan_version_id}' no es válido o no está activo.",
            )

    # 4. Validar TODOS los archivos antes de escribir cualquiera.
    archivos_validados = []
    for doc in documentos:
        validado = _validate_document(doc)
        if validado:
            archivos_validados.append(validado)

    request_id = str(uuid.uuid4())
    target_folder = os.path.join(upload_dir, request_id)
    docs_metadata = []

    for archivo in archivos_validados:
        os.makedirs(target_folder, exist_ok=True)
        safe_disk_name = f"{uuid.uuid4().hex}{archivo['ext']}"
        file_path = os.path.join(target_folder, safe_disk_name)
        with open(file_path, "wb") as f_out:
            f_out.write(archivo["content"])

        docs_metadata.append({
            "original_name": archivo["original_name"],
            "stored_path": file_path,
            "mime_type": archivo["mime_type"],
            "sha256": archivo["sha256"],
            "size": archivo["size"],
            "status": "UPLOADED",
        })

    # 5. Generación de código de seguimiento único y seguro
    tracking_code = f"TRK-{secrets.token_urlsafe(12)}"

    # 6. Guardar solicitud en estado PENDING con trazabilidad de seguridad
    new_request = TenantRequest(
        id_request=request_id,
        institucion_nombre=nombre.strip(),
        razon_social=razon_social.strip() if razon_social else None,
        nit=norm_nit,
        correo=correo.strip().lower(),
        telefono=telefono.strip() if telefono else None,
        direccion=direccion.strip() if direccion else None,
        responsable_nombre=responsable_nombre.strip(),
        responsable_correo=responsable_correo.strip().lower(),
        responsable_telefono=responsable_telefono.strip() if responsable_telefono else None,
        id_version_plan=plan_version_id,
        documentos_metadata=json.dumps(docs_metadata) if docs_metadata else None,
        tracking_code=tracking_code,
        status="PENDING",
        row_version=1,
        correlation_id=request_id,
        client_ip=(client_ip or "")[:45] or None,
        user_agent=(user_agent or "")[:512] or None,
    )

    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    logger.info(
        "Solicitud pública de alta registrada id=%s ip=%s archivos=%s",
        new_request.id_request,
        client_ip,
        len(docs_metadata),
    )

    return TenantRequestCreateResponse(
        id_request=new_request.id_request,
        tracking_code=new_request.tracking_code,
        status=new_request.status,
    )


def get_tracking_status(
    db: Session,
    tracking_code: str,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> TenantRequestTrackingResponse:
    if not tracking_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Código de seguimiento no encontrado",
        )

    _check_tracking_rate_limit(client_ip, tracking_code)
    req = db.query(TenantRequest).filter(
        TenantRequest.tracking_code == tracking_code.strip()
    ).first()

    if not req:
        _audit_tracking(
            db, tracking_code, "CONSULTAR_SEGUIMIENTO", "NO_ENCONTRADO",
            client_ip=client_ip, user_agent=user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Código de seguimiento no encontrado",
        )

    mensaje = "Su solicitud se encuentra en revisión por el equipo de administración."
    access_email = None
    temporary_password = None
    expires_at = None
    remaining_reveals = None

    if req.status == "APPROVED":
        mensaje = "Su solicitud ha sido aprobada. Use la credencial temporal para su primer ingreso."
        access_email = req.responsable_correo
        ahora = datetime.now(timezone.utc)
        expira = req.temporary_password_expires_at
        if expira is not None and expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)

        if req.credentials_issued and req.temporary_password_used_at is None and expira and ahora < expira:
            if req.temporary_password_reveal_count < settings.TEMP_CREDENTIAL_MAX_REVEALS:
                plaintext = decrypt_temporary_credential(req.temporary_password_encrypted or "")
                if plaintext:
                    req.temporary_password_reveal_count += 1
                    temporary_password = plaintext
                    expires_at = expira
                    remaining_reveals = (
                        settings.TEMP_CREDENTIAL_MAX_REVEALS - req.temporary_password_reveal_count
                    )
                    db.commit()
                    _audit_tracking(
                        db, tracking_code, "REVELAR_CREDENCIAL_TEMPORAL", "CONCEDIDA",
                        id_request=req.id_request, client_ip=client_ip, user_agent=user_agent,
                    )
                else:
                    _audit_tracking(
                        db, tracking_code, "REVELAR_CREDENCIAL_TEMPORAL", "ERROR_CIFRADO",
                        id_request=req.id_request, client_ip=client_ip, user_agent=user_agent,
                    )
            else:
                _audit_tracking(
                    db, tracking_code, "REVELAR_CREDENCIAL_TEMPORAL", "LIMITE_ALCANZADO",
                    id_request=req.id_request, client_ip=client_ip, user_agent=user_agent,
                )
        else:
            _audit_tracking(
                db, tracking_code, "REVELAR_CREDENCIAL_TEMPORAL", "NO_VIGENTE",
                id_request=req.id_request, client_ip=client_ip, user_agent=user_agent,
            )
    elif req.status == "REJECTED":
        if req.decision_motivo:
            mensaje = f"Su solicitud ha sido rechazada. Motivo: {req.decision_motivo}"
        else:
            mensaje = "Su solicitud ha sido rechazada. Comuníquese con soporte para más información."

    _audit_tracking(
        db, tracking_code, "CONSULTAR_SEGUIMIENTO", "ENCONTRADO",
        id_request=req.id_request, client_ip=client_ip, user_agent=user_agent,
    )
    return TenantRequestTrackingResponse(
        institucion=req.institucion_nombre,
        status=req.status,
        mensaje=mensaje,
        fecha_decision=req.decision_fecha,
        access_email=access_email,
        temporary_password=temporary_password,
        expires_at=expires_at,
        remaining_reveals=remaining_reveals,
    )
