"""Utilidades criptográficas Web Push: RFC 8291 (aes128gcm) y RFC 8292 (VAPID ES256)."""

from __future__ import annotations

import base64
import ipaddress
import os
import time
from typing import Dict
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from jose import jwt

from app.core.config import settings


def obtener_vapid_private_key() -> str:
    val = os.environ.get("VAPID_PRIVATE_KEY", settings.VAPID_PRIVATE_KEY or "")
    if "\\n" in val:
        val = val.replace("\\n", "\n")
    return val.strip()


def obtener_vapid_public_key() -> str:
    pub = os.environ.get("VAPID_PUBLIC_KEY", settings.VAPID_PUBLIC_KEY or "").strip()
    if pub:
        return pub
    priv = obtener_vapid_private_key()
    if priv:
        key = serialization.load_pem_private_key(priv.encode("utf-8"), password=None)
        pub_bytes = key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        return base64.urlsafe_b64encode(pub_bytes).decode("utf-8").rstrip("=")
    return ""


def generar_par_vapid() -> tuple[str, str]:
    """Genera un par de claves VAPID P-256 (public_key_b64, private_key_pem)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).decode("utf-8").rstrip("=")
    return pub_b64, pem


def es_url_segura_webpush(url_str: str) -> bool:
    """Exige HTTPS y bloquea IPs privadas, loopback o link-local para prevenir SSRF."""
    try:
        parsed = urlsplit(url_str)
        if parsed.scheme.lower() != "https":
            return False
        host = (parsed.hostname or "").lower().strip()
        if not host or host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "169.254.169.254"):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        except ValueError:
            # Nombre de dominio DNS válido
            if host.endswith(".local") or host.endswith(".internal"):
                return False
        return True
    except Exception:
        return False


def _b64decode_padding(s: str) -> bytes:
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    return base64.urlsafe_b64decode(s)


def cifrar_payload_webpush(
    payload_bytes: bytes,
    p256dh_b64: str,
    auth_b64: str,
) -> tuple[bytes, Dict[str, str]]:
    """Cifra el payload según RFC 8291 (aes128gcm) usando ECDH P-256 + HKDF-SHA256 + AESGCM."""
    client_pub_bytes = _b64decode_padding(p256dh_b64)
    client_auth = _b64decode_padding(auth_b64)

    client_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), client_pub_bytes)
    local_key = ec.generate_private_key(ec.SECP256R1())
    local_pub_bytes = local_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )

    shared_secret = local_key.exchange(ec.ECDH(), client_key)

    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=client_auth,
        info=b"WebPush: info\x00" + client_pub_bytes + local_pub_bytes,
    ).derive(shared_secret)

    salt = os.urandom(16)
    cek = HKDF(
        algorithm=hashes.SHA256(),
        length=16,
        salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(),
        length=12,
        salt=salt,
        info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)

    ciphertext = AESGCM(cek).encrypt(nonce, payload_bytes + b"\x02", None)
    rs = 4096
    header = salt + rs.to_bytes(4, "big") + len(local_pub_bytes).to_bytes(1, "big") + local_pub_bytes

    return header + ciphertext, {
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
    }


def generar_cabecera_vapid(
    endpoint: str,
    private_key_pem: str,
    public_key_b64: str,
    subject: str,
) -> str:
    """Firma el JWT ES256 para la cabecera Authorization VAPID (RFC 8292)."""
    parsed = urlsplit(endpoint)
    claims = {
        "aud": f"{parsed.scheme}://{parsed.netloc}",
        "exp": int(time.time()) + 86400,
        "sub": subject,
    }
    vapid_jwt = jwt.encode(claims, private_key_pem, algorithm="ES256")
    return f"vapid t={vapid_jwt}, k={public_key_b64}"
