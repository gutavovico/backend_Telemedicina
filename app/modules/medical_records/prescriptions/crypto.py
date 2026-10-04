"""Criptografía CU16: canonicalización RFC 8785 (JCS), firma Ed25519,
tokens públicos, anonimización HMAC y enmascaramiento de datos personales.

Ver specs/openspec/changes/cu16-recetas-digitales/design.md decisiones 2, 7 y 12.
"""
import base64
import hashlib
import hmac
import json
import secrets
from typing import Any, Dict, Tuple

from app.core.config import settings


PAYLOAD_VERSION = 1
SIGNATURE_ALGORITHM = "ED25519"
TOKEN_RANDOM_BYTES = 32
IDEMPOTENCY_WINDOW_HOURS = 24
TELEMETRY_RETENTION_DAYS = 30
RATE_LIMIT_PER_IP_PER_MINUTE = 30
RATE_LIMIT_PER_CODE_PER_MINUTE = 10


class PrescriptionCryptoError(Exception):
    """Error de configuración o verificación criptográfica de recetas."""


# --------------------------------------------------------------------------- #
# Canonicalización JSON RFC 8785 (JSON Canonicalization Scheme, JCS)
# Implementación delegada en la biblioteca mantenida `jcs` (RFC 8785),
# encapsulada detrás de `canonicalize_jcs()` para no acoplar el resto
# del módulo. Ver specs/openspec/changes/cu16-recetas-digitales/design.md
# decisión 2 y contrato prescriptions.md §5.
# --------------------------------------------------------------------------- #

def _assert_jcs_compatible(value: Any) -> None:
    """Valida tipos y rechaza NaN/infinitos antes de delegar en `jcs`.

    RFC 8785 no admite NaN ni infinitos; tampoco admite claves no
    textuales ni valores numéricos no interoperables en el payload
    clínico (aquí solo se esperan int/float finitos, str, bool, None,
    list/tuple y dict con claves str).
    """
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        # Rechazo explícito de no finitos (NaN, +inf, -inf).
        if value != value or value in (float("inf"), float("-inf")):
            raise PrescriptionCryptoError("Número no finito no permitido por RFC 8785")
        return
    if isinstance(value, str):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_jcs_compatible(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PrescriptionCryptoError("Las claves del payload deben ser cadenas")
            _assert_jcs_compatible(item)
        return
    raise PrescriptionCryptoError(f"Tipo no soportado en canonicalización: {type(value)}")


def canonicalize_jcs(payload: Any) -> bytes:
    """Serializa el payload a JSON canónico RFC 8785 codificado en UTF-8.

    Delega en `jcs.canonicalize()` (salida UTF-8 determinista, orden
    lexicográfico por unidades UTF-16, números ECMAScript, escapes
    correctos). Rechaza NaN e infinitos con error explícito.
    """
    _assert_jcs_compatible(payload)
    try:
        import jcs as _jcs_lib
    except Exception as exc:
        raise PrescriptionCryptoError(
            "Biblioteca RFC 8785 'jcs' no disponible; instale requirements.txt"
        ) from exc
    try:
        result = _jcs_lib.canonicalize(payload)
    except PrescriptionCryptoError:
        raise
    except ValueError as exc:
        # `jcs` rechaza NaN/inf con ValueError: normalizar al error de dominio.
        raise PrescriptionCryptoError("Número no finito no permitido por RFC 8785") from exc
    except Exception as exc:
        raise PrescriptionCryptoError(f"Canonicalización RFC 8785 fallida: {exc}") from exc
    if isinstance(result, str):
        return result.encode("utf-8")
    return bytes(result)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_hash(payload: Dict[str, Any]) -> str:
    """Hash RFC 8785 del cuerpo de emisión para detectar reutilización de Idempotency-Key."""
    return sha256_hex(canonicalize_jcs(payload))


# --------------------------------------------------------------------------- #
# Token público de verificación (32 bytes CSPRNG, Base64 URL-safe sin padding)
# --------------------------------------------------------------------------- #

def generate_verification_token() -> Tuple[str, str]:
    """Genera (token_publico, sha256_hex). Solo el hash se persiste en la base."""
    raw = secrets.token_bytes(TOKEN_RANDOM_BYTES)
    token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return token, hashlib.sha256(raw).hexdigest()


def hash_verification_token(token: str) -> str:
    """SHA-256 del token público tal como se persiste (hash del secreto de 256 bits)."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except Exception as exc:
        raise PrescriptionCryptoError("Código de verificación malformado") from exc
    if len(raw) != TOKEN_RANDOM_BYTES:
        raise PrescriptionCryptoError("Código de verificación malformado")
    return hashlib.sha256(raw).hexdigest()


# --------------------------------------------------------------------------- #
# Firma Ed25519 (cryptography) con anillo de claves para rotación
# --------------------------------------------------------------------------- #

def _load_private_key() -> Tuple[Any, str]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key_b64 = (settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 or "").strip()
    key_id = (settings.PRESCRIPTION_SIGNING_KEY_ID or "").strip()
    if not key_b64 or not key_id:
        raise PrescriptionCryptoError(
            "Configuración criptográfica incompleta: defina "
            "PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 y PRESCRIPTION_SIGNING_KEY_ID. "
            "El servicio de prescripciones no puede operar sin claves válidas."
        )
    try:
        raw = base64.b64decode(key_b64, validate=True)
    except Exception as exc:
        raise PrescriptionCryptoError("PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 no es Base64 válido") from exc
    if len(raw) != 32:
        raise PrescriptionCryptoError("La clave privada Ed25519 debe tener 32 bytes")
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(raw)
    except Exception as exc:
        raise PrescriptionCryptoError("Clave privada Ed25519 inválida") from exc
    return private_key, key_id


def _load_verification_ring() -> Dict[str, Any]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    raw_json = (settings.PRESCRIPTION_VERIFICATION_KEYS_JSON or "").strip()
    try:
        ring = json.loads(raw_json) if raw_json else {}
    except Exception as exc:
        raise PrescriptionCryptoError("PRESCRIPTION_VERIFICATION_KEYS_JSON no es JSON válido") from exc
    if not isinstance(ring, dict) or not ring:
        raise PrescriptionCryptoError(
            "El anillo de claves públicas está vacío: defina PRESCRIPTION_VERIFICATION_KEYS_JSON "
            "con la clave activa y las históricas."
        )
    private_key, active_key_id = _load_private_key()
    if active_key_id not in ring:
        raise PrescriptionCryptoError(
            f"La clave activa '{active_key_id}' no aparece en PRESCRIPTION_VERIFICATION_KEYS_JSON. "
            "La rotación exige conservar la clave pública activa en el anillo."
        )
    parsed: Dict[str, Any] = {}
    raw_by_kid: Dict[str, bytes] = {}
    for kid, pub_b64 in ring.items():
        if not isinstance(pub_b64, str) or not pub_b64.strip():
            raise PrescriptionCryptoError(f"Clave pública inválida para key_id '{kid}'")
        try:
            pub_raw = base64.b64decode(pub_b64.strip(), validate=True)
            parsed[kid] = Ed25519PublicKey.from_public_bytes(pub_raw)
            raw_by_kid[kid] = pub_raw
        except Exception as exc:
            raise PrescriptionCryptoError(f"Clave pública inválida para key_id '{kid}'") from exc
    # La clave pública del anillo debe corresponder con la privada activa.
    # Sin esta comprobación, el servicio firmaría con una clave que nunca
    # podría verificarse públicamente. No se registra material privado.
    try:
        derived_pub_raw = private_key.public_key().public_bytes_raw()
    except Exception as exc:
        raise PrescriptionCryptoError("Clave privada Ed25519 inválida") from exc
    if raw_by_kid.get(active_key_id) != derived_pub_raw:
        raise PrescriptionCryptoError(
            f"La clave pública del anillo para '{active_key_id}' no corresponde "
            "con la clave privada activa. Revise la rotación de claves."
        )
    return parsed


def ensure_prescription_crypto_configured() -> str:
    """Valida la configuración criptográfica; falla explícitamente si es inválida."""
    _, key_id = _load_private_key()
    _load_verification_ring()
    get_telemetry_hmac_key()
    return key_id


def sign_canonical_payload(canonical: bytes) -> Tuple[str, str]:
    """Firma el payload canónico; devuelve (firma_base64, key_id)."""
    private_key, key_id = _load_private_key()
    signature = private_key.sign(canonical)
    return base64.b64encode(signature).decode("ascii"), key_id


def verify_canonical_signature(key_id: str, canonical: bytes, signature_b64: str) -> bool:
    """Verifica la firma con la clave pública histórica identificada por key_id."""
    from cryptography.exceptions import InvalidSignature

    ring = _load_verification_ring()
    public_key = ring.get(key_id)
    if public_key is None:
        return False
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception:
        return False
    try:
        public_key.verify(signature, canonical)
        return True
    except InvalidSignature:
        return False


# --------------------------------------------------------------------------- #
# Anonimización y enmascaramiento (diseño decisiones 7 y 12)
# --------------------------------------------------------------------------- #

def get_telemetry_hmac_key() -> bytes:
    key = (settings.PRESCRIPTION_TELEMETRY_HMAC_KEY or "").strip()
    if not key:
        raise PrescriptionCryptoError(
            "Defina PRESCRIPTION_TELEMETRY_HMAC_KEY para anonimizar la IP "
            "en la telemetría de validación pública."
        )
    return key.encode("utf-8")


def anonymize_ip(client_ip: str) -> str:
    """HMAC-SHA256 de la IP: nunca se persiste la IP en claro."""
    return hmac.new(get_telemetry_hmac_key(), (client_ip or "").encode("utf-8"), hashlib.sha256).hexdigest()


def hash_idempotency_key(key: str) -> str:
    """SHA-256 de la Idempotency-Key: nunca se guarda la clave en claro."""
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def mask_patient_name(full_name: str) -> str:
    """Conserva el primer nombre y convierte el resto en iniciales: 'María Reneé Morales' → 'María R. M.'."""
    parts = (full_name or "").split()
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return parts[0] + " " + " ".join(p[0] + "." for p in parts[1:])


def mask_document(document: str) -> str:
    """Conserva solo los últimos tres caracteres; si tiene tres o menos, enmascara por completo."""
    doc = (document or "").strip()
    if len(doc) <= 3:
        return "*" * len(doc) if doc else ""
    return "*" * (len(doc) - 3) + doc[-3:]
