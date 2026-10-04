"""Servicio CU16: catálogo, emisión atómica, consulta, anulación y validación pública.

Toda la emisión (receta, detalles, archivo, documento clínico y auditoría)
se confirma en una única transacción sincronizada; ante un fallo posterior
a la escritura del archivo se ejecuta compensación (diseño § Atomicidad).
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, lazyload

from app.core.audit import registrar_auditoria
from app.modules.appointments.models import Especialidad, Medico, MedicoEspecialidad
from app.modules.auth.models import Clinica, Usuario
from app.modules.medical_records.clinical_documents.dependencies import (
    get_role_name,
    user_has_permission,
)
from app.modules.medical_records.clinical_documents.models import DocumentoClinico
from app.modules.medical_records.clinical_documents.storage import storage
from app.modules.medical_records.hce.models import Consulta, HistoriaClinica
from app.modules.medical_records.models import Paciente
from app.modules.medical_records.prescriptions import schemas
from app.modules.medical_records.prescriptions.crypto import (
    PAYLOAD_VERSION,
    SIGNATURE_ALGORITHM,
    anonymize_ip,
    canonicalize_jcs,
    ensure_prescription_crypto_configured,
    generate_verification_token,
    hash_idempotency_key,
    hash_verification_token,
    mask_document,
    mask_patient_name,
    request_hash,
    sha256_hex,
    sign_canonical_payload,
    verify_canonical_signature,
)
from app.modules.medical_records.prescriptions.dependencies import (
    PERMISO_CANCEL,
    PERMISO_DOWNLOAD,
    PERMISO_ISSUE,
    PERMISO_READ,
    is_admin_user,
)
from app.modules.medical_records.prescriptions.models import (
    ConfiguracionRecetas,
    Medicamento,
    Receta,
    RecetaDetalle,
    RecetaIdempotencia,
    RecetaValidacionIntento,
    SecuenciaRecetas,
)
from app.modules.medical_records.prescriptions.pdfgen import (
    RecetaPdfData,
    RecetaPdfDetalle,
    build_receta_pdf,
)
from app.modules.medical_records.prescriptions.qrcodegen import encode_qr_matrix
from app.core.config import settings


logger = logging.getLogger(__name__)

IDEMPOTENCY_WINDOW = timedelta(hours=24)
TELEMETRY_RETENTION = timedelta(days=30)
RATE_WINDOW = timedelta(seconds=60)
RATE_LIMIT_IP = 30
RATE_LIMIT_CODE = 10
MAX_EMIT_ATTEMPTS = 5


class PrescriptionError(Exception):
    """Error de dominio CU16 con código HTTP, mensaje y código de negocio."""

    def __init__(self, status_code: int, message: str, code: str = "PRESCRIPTION_ERROR",
                 headers: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code
        self.headers = headers or {}


def _today() -> date:
    return date.today()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _fecha_emision_iso(value) -> str:
    """ISO-8601 canónico en UTC sin microsegundos.

    El payload firmado debe ser reproducible desde los datos persistidos;
    la normalización evita diferencias de formato entre PostgreSQL y SQLite
    tras el roundtrip de fecha_emision.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return str(value)


def _is_postgres(db: Session) -> bool:
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:
        return False


def _q_receta(db: Session):
    """Query de Receta sin joinedloads que encadenen a Usuario.rol.

    El esquema físico de `roles` carece de `fecha_creacion` (divergencia
    pre-existente documentada en CU12); estos options hacen a CU16 robusto
    con o sin esa columna.
    """
    return db.query(Receta).options(lazyload(Receta.documento))


def _q_paciente(db: Session):
    return db.query(Paciente).options(lazyload(Paciente.usuario))


def _q_documento(db: Session):
    return db.query(DocumentoClinico).options(
        lazyload(DocumentoClinico.paciente), lazyload(DocumentoClinico.firmante))


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, IntegrityError):
        return False
    if isinstance(exc, OperationalError):
        text = str(exc).lower()
        return any(token in text for token in ("locked", "busy", "deadlock", "40001", "could not serialize"))
    return False


# --------------------------------------------------------------------------- #
# Perfiles y resolución de nombres
# --------------------------------------------------------------------------- #

def _require_clinica_activa(db: Session, tenant_id: Optional[int]) -> None:
    """Exige que la clínica del usuario exista y esté ACTIVA.

    Forma parte de la autorización CU16 (clínica activa del usuario);
    una clínica inactiva o inexistente no autoriza ninguna operación.
    """
    if tenant_id is None:
        raise PrescriptionError(400, "No fue posible resolver la clínica del usuario",
                                "PRESCRIPTION_VALIDATION")
    clinica = db.query(Clinica).filter(Clinica.id_clinica == tenant_id).first()
    if clinica is None or (clinica.estado or "").upper() != "ACTIVO":
        raise PrescriptionError(403, "La clínica del usuario no está activa",
                                "PRESCRIPTION_FORBIDDEN")


def _get_medico_profile(db: Session, user: Usuario, tenant_id: Optional[int]) -> Optional[Medico]:
    query = db.query(Medico).filter(Medico.id_usuario == user.id_usuario)
    medico = query.first()
    if medico is None:
        return None
    if tenant_id is not None and user.id_clinica is not None and user.id_clinica != tenant_id:
        return None
    return medico


def _require_medico_profile(db: Session, user: Usuario, tenant_id: Optional[int]) -> Medico:
    medico = _get_medico_profile(db, user, tenant_id)
    if medico is None:
        raise PrescriptionError(403, "El usuario autenticado no tiene perfil médico asociado",
                                "PRESCRIPTION_FORBIDDEN")
    return medico


def _get_patient_profile(db: Session, user: Usuario, tenant_id: Optional[int]) -> Optional[Paciente]:
    query = _q_paciente(db).filter(Paciente.id_usuario == user.id_usuario)
    if tenant_id is not None:
        query = query.filter(Paciente.id_clinica == tenant_id)
    return query.first()


def _medico_nombre(db: Session, medico: Medico) -> str:
    # SQL crudo: evita el joinedload de Usuario.rol, cuyo esquema ORM difiere
    # del físico en PostgreSQL (divergencia pre-existente documentada en CU12).
    from sqlalchemy import text as sql_text
    row = db.execute(
        sql_text("SELECT nombres, apellidos FROM usuarios WHERE id_usuario = :uid"),
        {"uid": medico.id_usuario},
    ).first()
    if row is None:
        return f"Médico {medico.id_medico}"
    return f"{row[0]} {row[1]}".strip()


def _medico_especialidad(db: Session, id_medico: int) -> Optional[str]:
    row = (
        db.query(Especialidad.nombre)
        .join(MedicoEspecialidad, MedicoEspecialidad.id_especialidad == Especialidad.id_especialidad)
        .filter(MedicoEspecialidad.id_medico == id_medico)
        .order_by(MedicoEspecialidad.es_principal.desc())
        .first()
    )
    return row[0] if row else None


def _paciente_nombre(paciente: Paciente) -> str:
    return f"{paciente.nombres} {paciente.apellidos}".strip()


def _paciente_documento(paciente: Paciente) -> str:
    doc = (paciente.ci or "").strip()
    if paciente.complemento:
        doc += str(paciente.complemento).strip()
    return doc


# --------------------------------------------------------------------------- #
# Catálogo global de medicamentos
# --------------------------------------------------------------------------- #

def _normalize_triple(nombre: str, concentracion: Optional[str], forma: Optional[str]) -> Tuple[str, str, str]:
    return (
        (nombre or "").strip().lower(),
        (concentracion or "").strip().lower(),
        (forma or "").strip().lower(),
    )


def crear_medicamento(db: Session, payload: schemas.MedicamentoCreate,
                      user: Usuario) -> Medicamento:
    nombre = payload.nombre.strip()
    triple = _normalize_triple(nombre, payload.concentracion, payload.forma_farmaceutica)
    candidatos = db.query(Medicamento).filter(func.lower(Medicamento.nombre) == triple[0]).all()
    for candidato in candidatos:
        if _normalize_triple(candidato.nombre, candidato.concentracion, candidato.forma_farmaceutica) == triple:
            raise PrescriptionError(409, "El medicamento ya existe en el catálogo",
                                    "PRESCRIPTION_CONFLICT")
    medicamento = Medicamento(
        nombre=nombre,
        principio_activo=(payload.principio_activo or "").strip() or None,
        concentracion=(payload.concentracion or "").strip() or None,
        forma_farmaceutica=(payload.forma_farmaceutica or "").strip() or None,
        descripcion=(payload.descripcion or "").strip() or None,
        estado="ACTIVO",
    )
    db.add(medicamento)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PrescriptionError(409, "El medicamento ya existe en el catálogo",
                                "PRESCRIPTION_CONFLICT") from exc
    db.refresh(medicamento)
    return medicamento


def listar_medicamentos(db: Session, query: Optional[str] = None, estado: Optional[str] = None,
                        skip: int = 0, limit: int = 50) -> Tuple[List[Medicamento], int]:
    q = db.query(Medicamento)
    estado_filtro = (estado or "ACTIVO").upper()
    if estado_filtro in ("ACTIVO", "INACTIVO"):
        q = q.filter(Medicamento.estado == estado_filtro)
    if query:
        like = f"%{query.strip()}%"
        q = q.filter(
            Medicamento.nombre.ilike(like) | Medicamento.principio_activo.ilike(like)
        )
    total = q.count()
    items = q.order_by(Medicamento.nombre).offset(skip).limit(limit).all()
    return items, total


# --------------------------------------------------------------------------- #
# Emisión
# --------------------------------------------------------------------------- #

def _global_vigencia_maxima() -> int:
    """Máximo global validado entre 1 y 90 días.

    Valida `PRESCRIPTION_DEFAULT_VALIDITY_DAYS` al cargar configuración:
    menor que 1 o mayor que 90 produce error explícito de configuración
    (nunca se usan valores inválidos silenciosamente).
    """
    try:
        valor = int(settings.PRESCRIPTION_DEFAULT_VALIDITY_DAYS)
    except Exception as exc:
        raise PrescriptionError(
            500,
            "Configuración inválida: PRESCRIPTION_DEFAULT_VALIDITY_DAYS debe ser entero entre 1 y 90",
            "PRESCRIPTION_CONFIG",
        ) from exc
    if valor < 1 or valor > 90:
        raise PrescriptionError(
            500,
            f"Configuración inválida: PRESCRIPTION_DEFAULT_VALIDITY_DAYS debe estar entre 1 y 90 (actual: {valor})",
            "PRESCRIPTION_CONFIG",
        )
    return valor


def _max_vigencia_dias(db: Session, tenant_id: int) -> int:
    """Máximo efectivo: min(90, global_validado, configuración_clínica).

    La configuración por clínica puede reducir el máximo, nunca ampliarlo.
    Ausencia de fila equivale al máximo global (por defecto 90).
    """
    global_max = _global_vigencia_maxima()
    row = db.query(ConfiguracionRecetas).filter(ConfiguracionRecetas.id_clinica == tenant_id).first()
    if row is not None:
        try:
            clinica_max = int(row.vigencia_maxima_dias)
        except Exception as exc:
            raise PrescriptionError(
                500,
                "Configuración inválida: configuracion_recetas.vigencia_maxima_dias fuera de 1-90",
                "PRESCRIPTION_CONFIG",
            ) from exc
        if clinica_max < 1 or clinica_max > 90:
            raise PrescriptionError(
                500,
                "Configuración inválida: configuracion_recetas.vigencia_maxima_dias debe estar entre 1 y 90",
                "PRESCRIPTION_CONFIG",
            )
        return min(90, global_max, clinica_max)
    return min(90, global_max)


def _validar_vigencia(db: Session, tenant_id: int, fecha_vencimiento: date, hoy: date) -> None:
    if fecha_vencimiento <= hoy:
        raise PrescriptionError(422, "La fecha de vencimiento debe ser posterior al día de emisión",
                                "PRESCRIPTION_VALIDATION")
    max_dias = _max_vigencia_dias(db, tenant_id)
    if (fecha_vencimiento - hoy).days > max_dias:
        raise PrescriptionError(
            422,
            f"La vigencia máxima para esta clínica es de {max_dias} días",
            "PRESCRIPTION_VALIDATION",
        )


def _reservar_folio(db: Session, tenant_id: int, anio: int) -> str:
    """Reserva atómica del siguiente folio REC-YYYY-NNNNNN por clínica/año.

    Estrategia segura para PostgreSQL (sin depender de un `flush` previo
    a `begin_nested()` y sin bloqueos globales en memoria):
    - `INSERT ... ON CONFLICT DO NOTHING` para inicializar el contador;
    - `SELECT ... FOR UPDATE` para bloquear la fila en la transacción;
    - incremento con `UPDATE` dentro de la misma transacción.
    Garantiza folio único por clínica/año, formato del contrato, ausencia
    de duplicados bajo concurrencia y rollback transaccional correcto.
    """
    from sqlalchemy import text as sql_text

    if _is_postgres(db):
        db.execute(
            sql_text(
                "INSERT INTO secuencias_recetas (id_clinica, anio, ultimo_numero) "
                "VALUES (:t, :a, 0) ON CONFLICT (id_clinica, anio) DO NOTHING"
            ),
            {"t": tenant_id, "a": anio},
        )
        row = db.execute(
            sql_text(
                "SELECT ultimo_numero FROM secuencias_recetas "
                "WHERE id_clinica = :t AND anio = :a FOR UPDATE"
            ),
            {"t": tenant_id, "a": anio},
        ).first()
        if row is None:
            raise PrescriptionError(500, "No fue posible reservar el folio de la receta",
                                    "PRESCRIPTION_ERROR")
        nuevo = int(row[0]) + 1
        db.execute(
            sql_text(
                "UPDATE secuencias_recetas SET ultimo_numero = :n "
                "WHERE id_clinica = :t AND anio = :a"
            ),
            {"n": nuevo, "t": tenant_id, "a": anio},
        )
        return f"REC-{anio}-{nuevo:06d}"
    # Variante SQLite (tests): INSERT OR IGNORE + SELECT + UPDATE en la
    # misma transacción; la contención concurrente se propaga como
    # OperationalError transitorio y la reintenta `emitir_receta()`.
    db.execute(
        sql_text(
            "INSERT OR IGNORE INTO secuencias_recetas (id_clinica, anio, ultimo_numero) "
            "VALUES (:t, :a, 0)"
        ),
        {"t": tenant_id, "a": anio},
    )
    row = db.execute(
        sql_text(
            "SELECT ultimo_numero FROM secuencias_recetas "
            "WHERE id_clinica = :t AND anio = :a"
        ),
        {"t": tenant_id, "a": anio},
    ).first()
    if row is None:
        raise PrescriptionError(500, "No fue posible reservar el folio de la receta",
                                "PRESCRIPTION_ERROR")
    nuevo = int(row[0]) + 1
    db.execute(
        sql_text(
            "UPDATE secuencias_recetas SET ultimo_numero = :n "
            "WHERE id_clinica = :t AND anio = :a"
        ),
        {"n": nuevo, "t": tenant_id, "a": anio},
    )
    return f"REC-{anio}-{nuevo:06d}"


def _build_canonical_dict(*, receta: Receta, detalles: List[RecetaDetalle],
                          matricula: str, fecha_emision_iso: str) -> Dict:
    return {
        "algoritmo_firma": SIGNATURE_ALGORITHM,
        "codigo_verificacion_hash": receta.codigo_verificacion_hash,
        "detalles": [
            {
                "cantidad": d.cantidad,
                "concentracion": d.concentracion,
                "dosis": d.dosis,
                "duracion": d.duracion,
                "forma_farmaceutica": d.forma_farmaceutica,
                "frecuencia": d.frecuencia,
                "id_medicamento": d.id_medicamento,
                "indicaciones": d.indicaciones,
                "medicamento_nombre": d.medicamento_nombre,
                "nombre_medicamento_manual": d.nombre_medicamento_manual,
                "posicion": d.posicion,
                "principio_activo": d.principio_activo,
                "via_administracion": d.via_administracion,
            }
            for d in sorted(detalles, key=lambda item: item.posicion)
        ],
        "fecha_emision": fecha_emision_iso,
        "fecha_vencimiento": receta.fecha_vencimiento.isoformat(),
        "folio": receta.folio,
        "id_clinica": receta.id_clinica,
        "id_consulta": receta.id_consulta,
        "id_medico": receta.id_medico,
        "id_paciente": receta.id_paciente,
        "indicaciones_generales": receta.indicaciones_generales,
        "key_id": receta.key_id,
        "matricula_profesional": matricula,
        "version_payload": PAYLOAD_VERSION,
    }


def _delete_stored_file(object_key: str) -> None:
    try:
        ok = storage.delete(object_key)
        if not ok:
            logger.warning("No fue posible compensar el archivo %s", object_key)
    except Exception as exc:  # la compensación nunca debe ocultar el error original
        logger.warning("No fue posible compensar el archivo %s: %s", object_key, exc)


def _validar_contexto_emision(db: Session, *, user: Usuario, tenant_id: int,
                              payload: schemas.RecetaCreateRequest) -> Tuple[Medico, Consulta, Paciente]:
    _require_clinica_activa(db, tenant_id)
    if not user_has_permission(db, user.id_rol, PERMISO_ISSUE):
        raise PrescriptionError(403, f"Permiso denegado. Se requiere el permiso '{PERMISO_ISSUE}'.",
                                "PRESCRIPTION_FORBIDDEN")
    medico = _require_medico_profile(db, user, tenant_id)

    consulta = db.query(Consulta).filter(Consulta.id_consulta == payload.id_consulta).first()
    if consulta is None or consulta.id_clinica != tenant_id:
        raise PrescriptionError(404, "Consulta no encontrada", "PRESCRIPTION_NOT_FOUND")
    if consulta.id_medico != medico.id_medico:
        raise PrescriptionError(403, "La consulta no está asignada al médico autenticado",
                                "PRESCRIPTION_FORBIDDEN")

    paciente = _q_paciente(db).filter(Paciente.id_paciente == payload.id_paciente).first()
    if paciente is None or paciente.id_clinica != tenant_id:
        raise PrescriptionError(404, "Paciente no encontrado", "PRESCRIPTION_NOT_FOUND")
    historia = db.query(HistoriaClinica).filter(
        HistoriaClinica.id_historia == consulta.id_historia
    ).first()
    if historia is None or historia.id_paciente != paciente.id_paciente:
        raise PrescriptionError(422, "La consulta no corresponde al paciente indicado",
                                "PRESCRIPTION_VALIDATION")
    return medico, consulta, paciente


def _construir_detalles(db: Session, detalles: List[schemas.RecetaDetalleCreate]) -> List[RecetaDetalle]:
    filas: List[RecetaDetalle] = []
    for posicion, item in enumerate(detalles, start=1):
        if item.id_medicamento is not None:
            medicamento = db.query(Medicamento).filter(
                Medicamento.id_medicamento == item.id_medicamento
            ).first()
            if medicamento is None:
                raise PrescriptionError(404, f"Medicamento {item.id_medicamento} no encontrado",
                                        "PRESCRIPTION_NOT_FOUND")
            if medicamento.estado != "ACTIVO":
                raise PrescriptionError(422, "El medicamento del catálogo no está activo",
                                        "PRESCRIPTION_VALIDATION")
            snapshot = {
                "medicamento_nombre": medicamento.nombre,
                "principio_activo": medicamento.principio_activo,
                "concentracion": medicamento.concentracion,
                "forma_farmaceutica": medicamento.forma_farmaceutica,
            }
        else:
            snapshot = {
                "medicamento_nombre": (item.nombre_medicamento_manual or "").strip(),
                "principio_activo": None,
                "concentracion": None,
                "forma_farmaceutica": None,
            }
        filas.append(RecetaDetalle(
            id_medicamento=item.id_medicamento,
            nombre_medicamento_manual=(item.nombre_medicamento_manual or "").strip() or None,
            dosis=item.dosis.strip(),
            frecuencia=item.frecuencia.strip(),
            duracion=item.duracion.strip(),
            via_administracion=item.via_administracion.value,
            cantidad=item.cantidad,
            indicaciones=(item.indicaciones or "").strip() or None,
            posicion=posicion,
            **snapshot,
        ))
    return filas


def emitir_receta(db: Session, *, user: Usuario, tenant_id: int,
                  payload: schemas.RecetaCreateRequest, payload_raw: Dict,
                  idempotency_key: str, client_ip: Optional[str]) -> Tuple[Receta, bool]:
    """Emite una receta en una única transacción. Retorna (receta, es_reintento)."""
    ensure_prescription_crypto_configured()
    if not idempotency_key or not idempotency_key.strip():
        raise PrescriptionError(422, "El header Idempotency-Key es obligatorio",
                                "PRESCRIPTION_VALIDATION")
    clave_hash = hash_idempotency_key(idempotency_key.strip())
    req_hash = request_hash(payload_raw)
    hoy = _today()

    last_error: Optional[BaseException] = None
    for _ in range(MAX_EMIT_ATTEMPTS):
        stored_keys: List[str] = []
        try:
            return _emitir_receta_tx(
                db, user=user, tenant_id=tenant_id, payload=payload,
                clave_hash=clave_hash, req_hash=req_hash, hoy=hoy,
                client_ip=client_ip, stored_keys=stored_keys,
            )
        except PrescriptionError:
            for object_key in stored_keys:
                _delete_stored_file(object_key)
            try:
                db.rollback()
            except Exception:
                pass
            raise
        except Exception as exc:  # noqa: BLE001 - compensación + reintento controlado
            for object_key in stored_keys:
                _delete_stored_file(object_key)
            try:
                db.rollback()
            except Exception:
                pass
            if _is_transient(exc):
                last_error = exc
                continue
            raise
    raise PrescriptionError(500, "No fue posible confirmar la emisión por contención concurrente",
                            "PRESCRIPTION_ERROR") from last_error


def _emitir_receta_tx(db: Session, *, user: Usuario, tenant_id: int,
                      payload: schemas.RecetaCreateRequest, clave_hash: str, req_hash: str,
                      hoy: date, client_ip: Optional[str], stored_keys: List[str]) -> Tuple[Receta, bool]:
    # Idempotencia: reintento idéntico devuelve la receta original (24 h)
    existente = db.query(RecetaIdempotencia).filter(
        RecetaIdempotencia.id_clinica == tenant_id,
        RecetaIdempotencia.id_usuario == user.id_usuario,
        RecetaIdempotencia.clave_hash == clave_hash,
    ).first()
    if existente is not None:
        if existente.expires_at is not None:
            expira = existente.expires_at
            if expira.tzinfo is None:
                expira = expira.replace(tzinfo=timezone.utc)
            if expira <= _now_utc():
                db.delete(existente)
                db.flush()
                existente = None
        if existente is not None:
            if existente.request_hash != req_hash:
                raise PrescriptionError(409, "La clave de idempotencia ya fue usada con otro contenido",
                                        "PRESCRIPTION_CONFLICT")
            receta_previa = _q_receta(db).filter(Receta.id_receta == existente.id_receta).first()
            if receta_previa is None or receta_previa.id_clinica != tenant_id:
                raise PrescriptionError(409, "La clave de idempotencia ya fue usada con otro contenido",
                                        "PRESCRIPTION_CONFLICT")
            return receta_previa, True

    medico, consulta, paciente = _validar_contexto_emision(
        db, user=user, tenant_id=tenant_id, payload=payload
    )
    _validar_vigencia(db, tenant_id, payload.fecha_vencimiento, hoy)
    filas_detalle = _construir_detalles(db, payload.detalles)

    anio = hoy.year
    folio = _reservar_folio(db, tenant_id, anio)
    token_publico, codigo_hash = generate_verification_token()
    ahora = _now_utc()

    receta = Receta(
        id_clinica=tenant_id,
        id_consulta=consulta.id_consulta,
        id_medico=medico.id_medico,
        id_paciente=paciente.id_paciente,
        folio=folio,
        codigo_verificacion_hash=codigo_hash,
        indicaciones_generales=(payload.indicaciones_generales or "").strip() or None,
        firma_digital="",
        algoritmo_firma=SIGNATURE_ALGORITHM,
        key_id="",
        version_payload=PAYLOAD_VERSION,
        hash_pdf="",
        fecha_emision=ahora,
        fecha_vencimiento=payload.fecha_vencimiento,
        estado="EMITIDA",
    )
    db.add(receta)
    db.flush()
    for fila in filas_detalle:
        fila.id_receta = receta.id_receta
        db.add(fila)
    db.flush()

    # El key_id forma parte del payload firmado: fijarlo ANTES de canonicalizar
    receta.key_id = ensure_prescription_crypto_configured()
    canonical = canonicalize_jcs(_build_canonical_dict(
        receta=receta, detalles=filas_detalle, matricula=medico.matricula_profesional,
        fecha_emision_iso=_fecha_emision_iso(ahora),
    ))
    firma_b64, key_id = sign_canonical_payload(canonical)
    receta.firma_digital = firma_b64
    receta.key_id = key_id

    base_url = (settings.PRESCRIPTION_PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
    validation_url = f"{base_url}/api/v1/recetas/validar/{token_publico}"
    qr_matrix, _qr_version = encode_qr_matrix(validation_url)
    clinica = db.query(Clinica).filter(Clinica.id_clinica == tenant_id).first()
    pdf_bytes = build_receta_pdf(RecetaPdfData(
        clinica_nombre=clinica.nombre if clinica else f"Clínica {tenant_id}",
        folio=folio,
        fecha_emision=ahora.date().isoformat(),
        fecha_vencimiento=payload.fecha_vencimiento.isoformat(),
        paciente_nombre=_paciente_nombre(paciente),
        medico_nombre=_medico_nombre(db, medico),
        medico_matricula=medico.matricula_profesional,
        medico_especialidad=_medico_especialidad(db, medico.id_medico) or "",
        id_consulta=consulta.id_consulta,
        indicaciones_generales=receta.indicaciones_generales,
        detalles=[
            RecetaPdfDetalle(
                nombre=d.medicamento_nombre, principio_activo=d.principio_activo,
                concentracion=d.concentracion, forma_farmaceutica=d.forma_farmaceutica,
                dosis=d.dosis, frecuencia=d.frecuencia, duracion=d.duracion,
                via_administracion=d.via_administracion, cantidad=d.cantidad,
                indicaciones=d.indicaciones,
            )
            for d in filas_detalle
        ],
        algoritmo_firma=SIGNATURE_ALGORITHM,
        key_id=key_id,
        firma_digital=firma_b64,
        validation_url=validation_url,
        qr_matrix=qr_matrix,
    ))
    object_key, pdf_sha = storage.store(f"receta_{folio}.pdf", pdf_bytes, "application/pdf")
    stored_keys.append(object_key)
    receta.hash_pdf = pdf_sha

    documento = DocumentoClinico(
        id_clinica=tenant_id,
        id_paciente=paciente.id_paciente,
        id_cita=None,
        tipo_documento="RECETA",
        titulo=f"Receta {folio}",
        descripcion=f"Receta médica digital {folio} de la consulta {consulta.id_consulta}",
        archivo_url=object_key,
        hash_archivo=pdf_sha,
        firmado_por=user.id_usuario,
        fecha_documento=hoy,
        metadatos={"folio": folio, "id_receta": receta.id_receta, "origen": "CU16"},
        estado="ACTIVO",
    )
    db.add(documento)
    db.flush()
    receta.id_documento = documento.id_documento

    registrar_auditoria(
        db, id_usuario=user.id_usuario, id_clinica=tenant_id,
        tabla_afectada="recetas", registro_id=receta.id_receta, accion="EMITIR_RECETA",
        descripcion=f"Emisión de receta {folio}",
        datos_nuevos={
            "folio": folio, "id_consulta": consulta.id_consulta,
            "id_paciente": paciente.id_paciente, "id_medico": medico.id_medico,
            "estado": "EMITIDA", "fecha_vencimiento": payload.fecha_vencimiento.isoformat(),
        },
        direccion_ip=client_ip,
    )
    db.add(RecetaIdempotencia(
        id_clinica=tenant_id, id_usuario=user.id_usuario, clave_hash=clave_hash,
        request_hash=req_hash, id_receta=receta.id_receta,
        expires_at=_now_utc() + IDEMPOTENCY_WINDOW,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        # Carrera de idempotencia: otra petición confirmó primero la misma
        # `Idempotency-Key` (comparación por hash de clave y hash de
        # solicitud). Se compensa el PDF de la petición perdedora antes de
        # devolver la receta ganadora; nunca se borra el PDF ganador.
        # La compensación se ejecuta tanto ante excepciones como ante este
        # retorno idempotente posterior al almacenamiento.
        perdedoras = list(stored_keys)
        stored_keys.clear()
        for object_key in perdedoras:
            _delete_stored_file(object_key)
        try:
            db.rollback()
        except Exception:
            pass
        # Otro intento concurrente confirmó primero: devolver la receta ganadora
        ganadora = db.query(RecetaIdempotencia).filter(
            RecetaIdempotencia.id_clinica == tenant_id,
            RecetaIdempotencia.id_usuario == user.id_usuario,
            RecetaIdempotencia.clave_hash == clave_hash,
        ).first()
        if ganadora is not None and ganadora.request_hash == req_hash and ganadora.id_receta:
            receta_ganadora = _q_receta(db).filter(Receta.id_receta == ganadora.id_receta).first()
            if receta_ganadora is not None:
                return receta_ganadora, True
        raise PrescriptionError(409, "La clave de idempotencia ya fue usada con otro contenido",
                                "PRESCRIPTION_CONFLICT") from exc

    db.refresh(receta)
    return receta, False


# --------------------------------------------------------------------------- #
# Consulta autenticada con alcance por rol
# --------------------------------------------------------------------------- #

def _receta_en_tenant(db: Session, id_receta: int, tenant_id: int) -> Optional[Receta]:
    receta = _q_receta(db).filter(Receta.id_receta == id_receta).first()
    if receta is None or receta.id_clinica != tenant_id:
        return None
    return receta


def _visibilidad_receta(db: Session, *, user: Usuario, tenant_id: int,
                        receta: Receta) -> str:
    """Retorna 'emisor' | 'paciente' | 'admin'. Lanza 403/404 según alcance.

    Autoriza por nombre normalizado del rol, permisos RBAC persistidos,
    clínica activa y propiedad/autoría del recurso; nunca por IDs fijos.
    """
    role_name = (get_role_name(db, user.id_rol) or "").upper()
    if role_name == "PACIENTE":
        perfil = _get_patient_profile(db, user, tenant_id)
        if perfil is None or perfil.id_paciente != receta.id_paciente:
            raise PrescriptionError(404, "Receta no encontrada", "PRESCRIPTION_NOT_FOUND")
        return "paciente"
    medico = _get_medico_profile(db, user, tenant_id)
    if medico is not None and medico.id_medico == receta.id_medico:
        return "emisor"
    if is_admin_user(db, user):
        return "admin"
    if medico is not None:
        raise PrescriptionError(403, "No tienes permiso para consultar esta receta",
                                "PRESCRIPTION_FORBIDDEN")
    raise PrescriptionError(403, "No tienes permiso para consultar esta receta",
                            "PRESCRIPTION_FORBIDDEN")


def listar_recetas(db: Session, *, user: Usuario, tenant_id: int,
                   id_paciente: Optional[int] = None, id_medico: Optional[int] = None,
                   estado: Optional[str] = None, desde: Optional[date] = None,
                   hasta: Optional[date] = None, skip: int = 0, limit: int = 50) -> Tuple[List[Receta], int]:
    _require_clinica_activa(db, tenant_id)
    if not user_has_permission(db, user.id_rol, PERMISO_READ):
        raise PrescriptionError(403, f"Permiso denegado. Se requiere el permiso '{PERMISO_READ}'.",
                                "PRESCRIPTION_FORBIDDEN")
    role_name = (get_role_name(db, user.id_rol) or "").upper()
    query = _q_receta(db).filter(Receta.id_clinica == tenant_id)
    if role_name == "PACIENTE":
        perfil = _get_patient_profile(db, user, tenant_id)
        if perfil is None:
            raise PrescriptionError(404, "Perfil de paciente no configurado para este usuario",
                                    "PRESCRIPTION_NOT_FOUND")
        # El paciente no puede ampliar el filtro: siempre sus recetas propias
        query = query.filter(Receta.id_paciente == perfil.id_paciente)
    elif role_name == "MEDICO":
        medico = _require_medico_profile(db, user, tenant_id)
        query = query.filter(Receta.id_medico == medico.id_medico)
    elif not is_admin_user(db, user):
        raise PrescriptionError(403, "No tienes permiso para listar recetas",
                                "PRESCRIPTION_FORBIDDEN")
    else:
        if id_paciente is not None:
            query = query.filter(Receta.id_paciente == id_paciente)
        if id_medico is not None:
            query = query.filter(Receta.id_medico == id_medico)
    if estado is not None:
        query = query.filter(Receta.estado == estado.upper())
    if desde is not None:
        query = query.filter(Receta.fecha_vencimiento >= desde)
    if hasta is not None:
        query = query.filter(Receta.fecha_vencimiento <= hasta)
    total = query.count()
    items = query.order_by(Receta.fecha_emision.desc(), Receta.id_receta.desc()).offset(skip).limit(limit).all()
    return items, total


def obtener_receta(db: Session, *, user: Usuario, tenant_id: int, id_receta: int,
                   client_ip: Optional[str], auditar: bool = True) -> Receta:
    _require_clinica_activa(db, tenant_id)
    if not user_has_permission(db, user.id_rol, PERMISO_READ):
        raise PrescriptionError(403, f"Permiso denegado. Se requiere el permiso '{PERMISO_READ}'.",
                                "PRESCRIPTION_FORBIDDEN")
    receta = _receta_en_tenant(db, id_receta, tenant_id)
    if receta is None:
        raise PrescriptionError(404, "Receta no encontrada", "PRESCRIPTION_NOT_FOUND")
    _visibilidad_receta(db, user=user, tenant_id=tenant_id, receta=receta)
    if auditar:
        registrar_auditoria(
            db, id_usuario=user.id_usuario, id_clinica=tenant_id,
            tabla_afectada="recetas", registro_id=receta.id_receta, accion="CONSULTAR_RECETA",
            descripcion=f"Consulta de receta {receta.folio}",
            datos_nuevos={"folio": receta.folio, "estado": receta.estado},
            direccion_ip=client_ip,
        )
        db.commit()
    return receta


def obtener_pdf_receta(db: Session, *, user: Usuario, tenant_id: int, id_receta: int,
                       client_ip: Optional[str]) -> Tuple[bytes, str]:
    _require_clinica_activa(db, tenant_id)
    receta = _receta_en_tenant(db, id_receta, tenant_id)
    if receta is None:
        raise PrescriptionError(404, "Receta no encontrada", "PRESCRIPTION_NOT_FOUND")
    # Alcance funcional (propiedad para pacientes, autoría para médicos,
    # misma clínica para administradores; nunca cross-tenant).
    _visibilidad_receta(db, user=user, tenant_id=tenant_id, receta=receta)
    # Toda descarga, incluido el paciente propietario, requiere
    # `prescriptions:download`. `prescriptions:read` solo permite
    # consultar listado o detalle.
    if not user_has_permission(db, user.id_rol, PERMISO_DOWNLOAD):
        raise PrescriptionError(403, f"Permiso denegado. Se requiere el permiso '{PERMISO_DOWNLOAD}'.",
                                "PRESCRIPTION_FORBIDDEN")
    documento = _q_documento(db).filter(
        DocumentoClinico.id_documento == receta.id_documento
    ).first() if receta.id_documento else None
    if documento is None:
        raise PrescriptionError(500, "El documento de la receta no está disponible",
                                "PRESCRIPTION_ERROR")
    contenido = storage.read(documento.archivo_url)
    if contenido is None:
        raise PrescriptionError(500, "El archivo de la receta no está disponible",
                                "PRESCRIPTION_ERROR")
    if sha256_hex(contenido) != receta.hash_pdf or sha256_hex(contenido) != documento.hash_archivo:
        raise PrescriptionError(500, "La integridad del archivo de la receta no pudo verificarse",
                                "PRESCRIPTION_ERROR")
    registrar_auditoria(
        db, id_usuario=user.id_usuario, id_clinica=tenant_id,
        tabla_afectada="recetas", registro_id=receta.id_receta, accion="DESCARGAR_RECETA",
        descripcion=f"Descarga de receta {receta.folio}",
        datos_nuevos={"folio": receta.folio},
        direccion_ip=client_ip,
    )
    db.commit()
    return contenido, receta.folio


# --------------------------------------------------------------------------- #
# Anulación
# --------------------------------------------------------------------------- #

def anular_receta(db: Session, *, user: Usuario, tenant_id: int, id_receta: int,
                  payload: schemas.RecetaAnulacionRequest, client_ip: Optional[str]) -> Receta:
    _require_clinica_activa(db, tenant_id)
    receta = _receta_en_tenant(db, id_receta, tenant_id)
    if receta is None:
        raise PrescriptionError(404, "Receta no encontrada", "PRESCRIPTION_NOT_FOUND")

    role_name = (get_role_name(db, user.id_rol) or "").upper()
    if role_name == "PACIENTE":
        perfil = _get_patient_profile(db, user, tenant_id)
        if perfil is None or perfil.id_paciente != receta.id_paciente:
            raise PrescriptionError(404, "Receta no encontrada", "PRESCRIPTION_NOT_FOUND")
        raise PrescriptionError(403, "No tienes permiso para anular esta receta",
                                "PRESCRIPTION_FORBIDDEN")
    medico = _get_medico_profile(db, user, tenant_id)
    es_emisor = medico is not None and medico.id_medico == receta.id_medico
    es_admin_autorizado = is_admin_user(db, user) and user_has_permission(db, user.id_rol, PERMISO_CANCEL)
    if not (es_emisor or es_admin_autorizado):
        raise PrescriptionError(403, "Solo el médico emisor o un administrador con "
                                     "'prescriptions:cancel' puede anular la receta",
                                "PRESCRIPTION_FORBIDDEN")

    if receta.estado == "ANULADA":
        raise PrescriptionError(409, "La receta ya se encuentra anulada", "PRESCRIPTION_CONFLICT")
    if receta.fecha_vencimiento < _today():
        raise PrescriptionError(409, "No es posible anular una receta vencida", "PRESCRIPTION_CONFLICT")

    sustituta_id = None
    if payload.id_receta_sustituta is not None:
        if payload.id_receta_sustituta == receta.id_receta:
            raise PrescriptionError(409, "La receta no puede sustituirse a sí misma",
                                    "PRESCRIPTION_CONFLICT")
        sustituta = _q_receta(db).filter(
            Receta.id_receta == payload.id_receta_sustituta
        ).first()
        if sustituta is None or sustituta.id_clinica != tenant_id:
            raise PrescriptionError(404, "Receta sustituta no encontrada", "PRESCRIPTION_NOT_FOUND")
        if sustituta.id_paciente != receta.id_paciente:
            raise PrescriptionError(409, "La receta sustituta debe pertenecer al mismo paciente",
                                    "PRESCRIPTION_CONFLICT")
        visitada = set()
        actual: Optional[Receta] = sustituta
        while actual is not None and actual.id_receta not in visitada:
            if actual.id_receta == receta.id_receta:
                raise PrescriptionError(409, "La sustitución forma un ciclo",
                                        "PRESCRIPTION_CONFLICT")
            visitada.add(actual.id_receta)
            actual = _q_receta(db).filter(
                Receta.id_receta == actual.id_receta_sustituta
            ).first() if actual.id_receta_sustituta else None
        sustituta_id = sustituta.id_receta

    estado_anterior = receta.estado
    receta.estado = "ANULADA"
    receta.motivo_anulacion = payload.motivo_anulacion.strip()
    receta.observaciones_anulacion = (payload.observaciones_anulacion or "").strip() or None
    receta.fecha_anulacion = _now_utc()
    receta.anulado_por = user.id_usuario
    receta.id_receta_sustituta = sustituta_id

    documento = _q_documento(db).filter(
        DocumentoClinico.id_documento == receta.id_documento
    ).first() if receta.id_documento else None
    if documento is None:
        raise PrescriptionError(500, "El documento de la receta no está disponible",
                                "PRESCRIPTION_ERROR")
    documento.estado = "ANULADO"

    registrar_auditoria(
        db, id_usuario=user.id_usuario, id_clinica=tenant_id,
        tabla_afectada="recetas", registro_id=receta.id_receta, accion="ANULAR_RECETA",
        descripcion=f"Anulación de receta {receta.folio}",
        datos_anteriores={"estado": estado_anterior},
        datos_nuevos={"estado": "ANULADA", "motivo_anulacion": receta.motivo_anulacion,
                      "id_receta_sustituta": sustituta_id},
        direccion_ip=client_ip,
    )
    db.commit()
    db.refresh(receta)
    return receta


# --------------------------------------------------------------------------- #
# Validación pública
# --------------------------------------------------------------------------- #

def _purge_telemetry(db: Session, ahora: datetime) -> None:
    db.query(RecetaValidacionIntento).filter(
        RecetaValidacionIntento.fecha_hora < (ahora - TELEMETRY_RETENTION)
    ).delete(synchronize_session=False)


def validar_publica(db: Session, codigo: str, client_ip: str) -> Dict:
    """Validación pública anonimizada con rate limiting PostgreSQL/SQLite."""
    ensure_prescription_crypto_configured()
    ahora = _now_utc()
    hoy = _today()
    _purge_telemetry(db, ahora)

    try:
        codigo_hash = hash_verification_token(codigo or "")
    except Exception:
        codigo_hash = sha256_hex((codigo or "").encode("utf-8"))
    ip_hash = anonymize_ip(client_ip or "desconocida")
    ventana_desde = ahora - RATE_WINDOW

    intentos_ip = db.query(RecetaValidacionIntento).filter(
        RecetaValidacionIntento.ip_hash == ip_hash,
        RecetaValidacionIntento.fecha_hora >= ventana_desde,
    ).count()
    if intentos_ip >= RATE_LIMIT_IP:
        mas_antiguo = db.query(RecetaValidacionIntento.fecha_hora).filter(
            RecetaValidacionIntento.ip_hash == ip_hash,
            RecetaValidacionIntento.fecha_hora >= ventana_desde,
        ).order_by(RecetaValidacionIntento.fecha_hora).first()
        retry_after = 60
        if mas_antiguo and mas_antiguo[0] is not None:
            marca = mas_antiguo[0]
            if marca.tzinfo is None:
                marca = marca.replace(tzinfo=timezone.utc)
            retry_after = max(1, 60 - int((ahora - marca).total_seconds()))
        raise PrescriptionError(429, "Demasiadas solicitudes de validación",
                                "PRESCRIPTION_RATE_LIMITED",
                                headers={"Retry-After": str(retry_after)})

    intentos_codigo = db.query(RecetaValidacionIntento).filter(
        RecetaValidacionIntento.codigo_hash == codigo_hash,
        RecetaValidacionIntento.fecha_hora >= ventana_desde,
    ).count()
    if intentos_codigo >= RATE_LIMIT_CODE:
        mas_antiguo = db.query(RecetaValidacionIntento.fecha_hora).filter(
            RecetaValidacionIntento.codigo_hash == codigo_hash,
            RecetaValidacionIntento.fecha_hora >= ventana_desde,
        ).order_by(RecetaValidacionIntento.fecha_hora).first()
        retry_after = 60
        if mas_antiguo and mas_antiguo[0] is not None:
            marca = mas_antiguo[0]
            if marca.tzinfo is None:
                marca = marca.replace(tzinfo=timezone.utc)
            retry_after = max(1, 60 - int((ahora - marca).total_seconds()))
        raise PrescriptionError(429, "Demasiadas solicitudes de validación",
                                "PRESCRIPTION_RATE_LIMITED",
                                headers={"Retry-After": str(retry_after)})

    receta = _q_receta(db).filter(
        Receta.codigo_verificacion_hash == codigo_hash
    ).first()

    if receta is None:
        db.add(RecetaValidacionIntento(codigo_hash=codigo_hash, ip_hash=ip_hash,
                                       resultado="NO_ENCONTRADA"))
        db.commit()
        return {"valida": False, "estado": "NO_ENCONTRADA"}

    # Validación pública de integridad: antes de responder `valida: true`
    # (y antes de exponer cualquier detalle clínico) se comprueba firma
    # Ed25519 del payload reconstruido, key_id en el anillo, algoritmo y
    # versión, SHA-256 del PDF, coincidencia hash_pdf/documento y lectura
    # correcta. Reutiliza `verificar_integridad_receta()` sin duplicar
    # lógica criptográfica. Si falla: no se presenta como válida, no se
    # exponen detalles manipulados, se responde con el estado público
    # uniforme del contrato, se registra telemetría anonimizada y no se
    # atribuye a usuario clínico inexistente (sin `auditoria`).
    try:
        integra = verificar_integridad_receta(db, receta)
    except Exception:
        integra = False
    if not integra:
        logger.warning("Validación pública con integridad fallida para hash %s", codigo_hash[:12])
        db.add(RecetaValidacionIntento(codigo_hash=codigo_hash, ip_hash=ip_hash,
                                       resultado="NO_ENCONTRADA"))
        db.commit()
        return {"valida": False, "estado": "NO_ENCONTRADA"}

    if receta.estado == "ANULADA":
        estado_publico, valida = "ANULADA", False
    elif receta.fecha_vencimiento < hoy:
        estado_publico, valida = "VENCIDA", False
    else:
        estado_publico, valida = "EMITIDA", True

    paciente = _q_paciente(db).filter(Paciente.id_paciente == receta.id_paciente).first()
    medico = db.query(Medico).filter(Medico.id_medico == receta.id_medico).first()
    clinica = db.query(Clinica).filter(Clinica.id_clinica == receta.id_clinica).first()
    detalles = db.query(RecetaDetalle).filter(
        RecetaDetalle.id_receta == receta.id_receta
    ).order_by(RecetaDetalle.posicion).all()

    nombre_medico = _medico_nombre(db, medico) if medico else f"Médico {receta.id_medico}"
    matricula = medico.matricula_profesional if medico else ""
    nombre_paciente = _paciente_nombre(paciente) if paciente else ""
    documento = _paciente_documento(paciente) if paciente else ""
    medicamentos_pub = []
    for det in detalles:
        titulo = det.medicamento_nombre
        if det.concentracion:
            titulo += f" ({det.concentracion})"
        medicamentos_pub.append({
            "medicamento": titulo,
            "posologia": (
                f"{det.dosis} {det.frecuencia} {det.duracion}, "
                f"vía {det.via_administracion.lower()}"
            ),
            "cantidad": det.cantidad,
            "indicaciones": det.indicaciones,
        })

    db.add(RecetaValidacionIntento(codigo_hash=codigo_hash, ip_hash=ip_hash,
                                   resultado=estado_publico))
    db.commit()
    return {
        "valida": valida,
        "estado": estado_publico,
        "folio": receta.folio,
        "fecha_emision": receta.fecha_emision.date().isoformat()
        if isinstance(receta.fecha_emision, datetime) else str(receta.fecha_emision)[:10],
        "fecha_vencimiento": receta.fecha_vencimiento.isoformat(),
        "esta_vencida": receta.fecha_vencimiento < hoy,
        "institucion": clinica.nombre if clinica else "",
        "medico_emisor": {
            "nombre": nombre_medico,
            "matricula": matricula,
            "especialidad": _medico_especialidad(db, receta.id_medico) if medico else None,
        },
        "paciente": {
            "nombre": mask_patient_name(nombre_paciente),
            "documento_identidad": mask_document(documento),
        },
        "medicamentos_prescritos": medicamentos_pub,
    }


def verificar_integridad_receta(db: Session, receta: Receta) -> bool:
    """Verifica integridad criptográfica y documental antes de presentar como válida.

    Comprueba, en orden y sin duplicar lógica criptográfica fuera de
    `verify_canonical_signature()`/`canonicalize_jcs()`:
    - algoritmo y versión del payload (`ED25519`, `PAYLOAD_VERSION`);
    - existencia del `key_id` en el anillo público (vía verificación);
    - firma Ed25519 del payload clínico reconstruido;
    - SHA-256 del PDF almacenado;
    - coincidencia `recetas.hash_pdf` con `documentos_clinicos.hash_archivo`;
    - existencia y lectura correcta del documento.
    Cualquier fallo retorna False sin exponer detalles internos.
    """
    try:
        if receta is None:
            return False
        if (receta.algoritmo_firma or "") != SIGNATURE_ALGORITHM:
            return False
        try:
            version = int(receta.version_payload)
        except Exception:
            return False
        if version != int(PAYLOAD_VERSION):
            return False
        if not receta.key_id or not receta.firma_digital or not receta.hash_pdf:
            return False
        detalles = db.query(RecetaDetalle).filter(
            RecetaDetalle.id_receta == receta.id_receta
        ).order_by(RecetaDetalle.posicion).all()
        medico = db.query(Medico).filter(Medico.id_medico == receta.id_medico).first()
        matricula = medico.matricula_profesional if medico else ""
        canonical = canonicalize_jcs(_build_canonical_dict(
            receta=receta, detalles=detalles, matricula=matricula,
            fecha_emision_iso=_fecha_emision_iso(receta.fecha_emision),
        ))
        if not verify_canonical_signature(receta.key_id, canonical, receta.firma_digital):
            return False
        documento = _q_documento(db).filter(
            DocumentoClinico.id_documento == receta.id_documento
        ).first() if receta.id_documento else None
        if documento is None or not documento.hash_archivo or not documento.archivo_url:
            return False
        if documento.hash_archivo != receta.hash_pdf:
            return False
        try:
            contenido = storage.read(documento.archivo_url)
        except Exception:
            return False
        if contenido is None or sha256_hex(contenido) != receta.hash_pdf:
            return False
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Serialización de respuestas
# --------------------------------------------------------------------------- #

def receta_to_response(db: Session, receta: Receta) -> schemas.RecetaResponse:
    detalles = db.query(RecetaDetalle).filter(
        RecetaDetalle.id_receta == receta.id_receta
    ).order_by(RecetaDetalle.posicion).all()
    medico = db.query(Medico).filter(Medico.id_medico == receta.id_medico).first()
    paciente = _q_paciente(db).filter(Paciente.id_paciente == receta.id_paciente).first()
    matricula = medico.matricula_profesional if medico else ""
    return schemas.RecetaResponse(
        id_receta=receta.id_receta,
        id_clinica=receta.id_clinica,
        id_consulta=receta.id_consulta,
        id_paciente=receta.id_paciente,
        id_medico=receta.id_medico,
        id_documento=receta.id_documento,
        id_receta_sustituta=receta.id_receta_sustituta,
        folio=receta.folio,
        pdf_url=f"/api/v1/recetas/{receta.id_receta}/pdf",
        indicaciones_generales=receta.indicaciones_generales,
        algoritmo_firma=receta.algoritmo_firma,
        key_id=receta.key_id,
        version_payload=receta.version_payload,
        hash_pdf=receta.hash_pdf,
        fecha_emision=receta.fecha_emision.isoformat() if isinstance(receta.fecha_emision, datetime) else str(receta.fecha_emision),
        fecha_vencimiento=receta.fecha_vencimiento.isoformat(),
        esta_vencida=receta.fecha_vencimiento < _today(),
        estado=receta.estado,
        motivo_anulacion=receta.motivo_anulacion,
        observaciones_anulacion=receta.observaciones_anulacion,
        fecha_anulacion=receta.fecha_anulacion.isoformat() if isinstance(receta.fecha_anulacion, datetime) else None,
        medico=schemas.MedicoResumen(
            id_medico=receta.id_medico,
            nombre_completo=_medico_nombre(db, medico) if medico else "",
            matricula_profesional=matricula,
            especialidad=_medico_especialidad(db, receta.id_medico) if medico else None,
        ),
        paciente=schemas.PacienteResumen(
            id_paciente=receta.id_paciente,
            nombre_completo=_paciente_nombre(paciente) if paciente else "",
        ),
        detalles=[schemas.RecetaDetalleResponse.model_validate(d) for d in detalles],
    )
