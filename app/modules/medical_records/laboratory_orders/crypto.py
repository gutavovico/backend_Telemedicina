"""Criptografía para firma digital de órdenes de laboratorio (CU10).

Usa HMAC-SHA256 con clave derivada por médico vía HKDF desde JWT_SECRET_KEY.
La clave maestra (JWT_SECRET_KEY) ya existe en config y se rota periódicamente.
"""

import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings


def _derive_signing_key(medico_id: int) -> bytes:
    """Deriva clave de firma de 32 bytes para un médico específico.

    HKDF-SHA256(salt="lab-order-sign", info=medico_id, IKM=JWT_SECRET_KEY)
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"lab-order-sign",
        info=str(medico_id).encode(),
    )
    return hkdf.derive(settings.JWT_SECRET_KEY.encode())


def _canonical_payload(
    id_orden: int,
    id_paciente: int,
    id_medico: int,
    examenes: List[Dict[str, Any]],
    fecha_orden: date,
    timestamp_firma: str,
) -> bytes:
    """Genera payload canónico ordenado (JSON sin espacios) para firma."""
    payload = {
        "id_orden": id_orden,
        "id_paciente": id_paciente,
        "id_medico": id_medico,
        "examenes": sorted(examenes, key=lambda x: x["codigo"]),
        "fecha_orden": fecha_orden.isoformat(),
        "timestamp_firma": timestamp_firma,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def sign_order(
    id_orden: int,
    id_paciente: int,
    id_medico: int,
    examenes: List[Dict[str, Any]],
    fecha_orden: date,
) -> tuple[str, str]:
    """Firma una orden de laboratorio.

    Returns:
        tuple: (firma_digital_hex, timestamp_firma_iso)
    """
    timestamp_firma = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    key = _derive_signing_key(id_medico)
    canonical = _canonical_payload(id_orden, id_paciente, id_medico, examenes, fecha_orden, timestamp_firma)
    firma = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return firma, timestamp_firma


def verify_signature(
    id_orden: int,
    id_paciente: int,
    id_medico: int,
    examenes: List[Dict[str, Any]],
    fecha_orden: date,
    timestamp_firma: str,
    firma_esperada: str,
) -> bool:
    """Verifica la firma HMAC de una orden."""
    key = _derive_signing_key(id_medico)
    canonical = _canonical_payload(id_orden, id_paciente, id_medico, examenes, fecha_orden, timestamp_firma)
    firma_calculada = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(firma_calculada, firma_esperada)