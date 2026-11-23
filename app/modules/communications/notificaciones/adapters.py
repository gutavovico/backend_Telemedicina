"""Adaptadores multicanal de entrega (CU20): WebPush PWA, FCM v1 Móvil, Email y SMS."""

from __future__ import annotations

import json
import logging
import os
import smtplib
import time
import uuid
from email.message import EmailMessage
from typing import Any, Dict, Optional

import httpx
from jose import jwt
from pydantic import BaseModel

from app.core.config import settings
from app.core.sms import get_sms_provider
from app.modules.communications.notificaciones.crypto_webpush import (
    cifrar_payload_webpush,
    es_url_segura_webpush,
    generar_cabecera_vapid,
    obtener_vapid_private_key,
    obtener_vapid_public_key,
)

logger = logging.getLogger("notificaciones.adapters")


class DeliveryResult(BaseModel):
    exito: bool
    codigo: str  # ACEPTADO | TOKEN_INVALIDO | RATE_LIMITED | TIMEOUT | NO_CONFIGURADO | DESTINO_INVALIDO | ERROR_PROVEEDOR
    token_invalido: bool = False
    reintentable: bool = False
    mensaje_id: Optional[str] = None
    detalle: Optional[str] = None


class WebPushAdapter:
    """Entrega Push a navegadores Web PWA usando RFC 8291 (aes128gcm) + RFC 8292 (VAPID ES256)."""

    def __init__(self, http_client: Optional[httpx.Client] = None):
        self.http_client = http_client

    def enviar(self, token: str, titulo: str, cuerpo: str, payload: Dict[str, Any]) -> DeliveryResult:
        vapid_private = obtener_vapid_private_key()
        vapid_public = obtener_vapid_public_key()
        if not vapid_private or not vapid_public:
            return DeliveryResult(exito=False, codigo="NO_CONFIGURADO", detalle="Faltan claves VAPID")

        try:
            sub_data = json.loads(token)
            endpoint = sub_data["endpoint"]
            p256dh = sub_data["keys"]["p256dh"]
            auth_key = sub_data["keys"]["auth"]
        except Exception:
            return DeliveryResult(
                exito=False,
                codigo="TOKEN_INVALIDO",
                token_invalido=True,
                detalle="Suscripción Web Push malformada",
            )

        if not es_url_segura_webpush(endpoint):
            return DeliveryResult(
                exito=False,
                codigo="DESTINO_INVALIDO",
                detalle="Endpoint rechazado por validación HTTPS/SSRF",
            )

        clean_data = {
            str(k): str(v)
            for k, v in payload.items()
            if not str(k).startswith("_") and v is not None
        }
        payload_bytes = json.dumps(
            {
                "title": titulo,
                "body": cuerpo,
                "data": clean_data,
                "tag": clean_data.get("tipo", "telemedicina-notificacion"),
            },
            ensure_ascii=False,
        ).encode("utf-8")

        subject = os.environ.get("VAPID_SUBJECT", settings.VAPID_SUBJECT)
        auth_header = generar_cabecera_vapid(endpoint, vapid_private, vapid_public, subject)
        body_encrypted, enc_headers = cifrar_payload_webpush(payload_bytes, p256dh, auth_key)
        headers = {"TTL": "60", "Authorization": auth_header, **enc_headers}

        client = self.http_client or httpx.Client(timeout=8.0, follow_redirects=False)
        close_after = self.http_client is None
        try:
            resp = client.post(endpoint, headers=headers, content=body_encrypted)
            if resp.status_code in (200, 201, 202):
                return DeliveryResult(exito=True, codigo="ACEPTADO", mensaje_id=f"wp_{uuid.uuid4().hex[:12]}")
            if resp.status_code in (404, 410):
                return DeliveryResult(
                    exito=False,
                    codigo="TOKEN_INVALIDO",
                    token_invalido=True,
                    detalle=f"HTTP {resp.status_code}",
                )
            if resp.status_code == 429:
                return DeliveryResult(exito=False, codigo="RATE_LIMITED", reintentable=True, detalle="HTTP 429")
            return DeliveryResult(
                exito=False,
                codigo="ERROR_PROVEEDOR",
                reintentable=resp.status_code >= 500,
                detalle=f"HTTP {resp.status_code}",
            )
        except httpx.TimeoutException:
            return DeliveryResult(exito=False, codigo="TIMEOUT", reintentable=True, detalle="Timeout WebPush")
        except Exception as exc:
            return DeliveryResult(exito=False, codigo="ERROR_PROVEEDOR", reintentable=True, detalle=str(exc)[:180])
        finally:
            if close_after:
                client.close()


class FCMPushAdapter:
    """Entrega Push a dispositivos móviles Flutter vía Firebase Cloud Messaging HTTP v1 (OAuth2 RS256)."""

    def __init__(self, http_client: Optional[httpx.Client] = None):
        self.http_client = http_client
        self._token_cache: Optional[Dict[str, Any]] = None

    def _cargar_service_account(self) -> Optional[Dict[str, Any]]:
        cred_json = os.environ.get("FCM_SERVICE_ACCOUNT_JSON", settings.FCM_SERVICE_ACCOUNT_JSON or "").strip()
        if cred_json:
            return json.loads(cred_json)
        for path_candidate in (
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", settings.GOOGLE_APPLICATION_CREDENTIALS or "").strip(),
            (settings.CU17_FCM_SERVICE_ACCOUNT_FILE or "").strip(),
        ):
            if path_candidate and os.path.isfile(path_candidate):
                with open(path_candidate, "r", encoding="utf-8") as fh:
                    return json.load(fh)
        return None

    def _obtener_oauth2_token(self, client: httpx.Client) -> Optional[tuple[str, str]]:
        ahora = time.time()
        if self._token_cache and self._token_cache.get("expira_en", 0) > ahora + 60:
            return self._token_cache["access_token"], self._token_cache["project_id"]

        sa_data = self._cargar_service_account()
        if not sa_data:
            return None

        project_id = (
            sa_data.get("project_id")
            or os.environ.get("FCM_PROJECT_ID", settings.FCM_PROJECT_ID)
            or settings.CU17_FCM_PROJECT_ID
        )
        if not project_id:
            return None

        token_uri = sa_data.get("token_uri", "https://oauth2.googleapis.com/token")
        now_int = int(ahora)
        assertion = jwt.encode(
            {
                "iss": sa_data["client_email"],
                "scope": "https://www.googleapis.com/auth/firebase.messaging",
                "aud": token_uri,
                "exp": now_int + 3600,
                "iat": now_int,
            },
            sa_data["private_key"],
            algorithm="RS256",
        )

        resp = client.post(
            token_uri,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        self._token_cache = {
            "access_token": data["access_token"],
            "project_id": project_id,
            "expira_en": ahora + data.get("expires_in", 3600),
        }
        return data["access_token"], project_id

    def enviar(self, token: str, titulo: str, cuerpo: str, payload: Dict[str, Any]) -> DeliveryResult:
        client = self.http_client or httpx.Client(timeout=8.0)
        close_after = self.http_client is None
        try:
            token_info = self._obtener_oauth2_token(client)
            if not token_info:
                return DeliveryResult(exito=False, codigo="NO_CONFIGURADO", detalle="Faltan credenciales FCM")

            access_token, project_id = token_info
            url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
            body = {
                "message": {
                    "token": token,
                    "notification": {"title": titulo, "body": cuerpo},
                    "data": {
                        str(k): str(v)
                        for k, v in payload.items()
                        if not str(k).startswith("_") and v is not None
                    },
                }
            }
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; UTF-8"},
                json=body,
            )
            if resp.status_code in (200, 201):
                return DeliveryResult(exito=True, codigo="ACEPTADO", mensaje_id=resp.json().get("name"))
            if resp.status_code in (404, 410):
                return DeliveryResult(exito=False, codigo="TOKEN_INVALIDO", token_invalido=True, detalle=f"HTTP {resp.status_code}")
            if resp.status_code == 429:
                return DeliveryResult(exito=False, codigo="RATE_LIMITED", reintentable=True)
            return DeliveryResult(
                exito=False,
                codigo="ERROR_PROVEEDOR",
                reintentable=resp.status_code >= 500,
                detalle=f"HTTP {resp.status_code}",
            )
        except httpx.TimeoutException:
            return DeliveryResult(exito=False, codigo="TIMEOUT", reintentable=True)
        except Exception as exc:
            return DeliveryResult(exito=False, codigo="ERROR_PROVEEDOR", reintentable=True, detalle=str(exc)[:180])
        finally:
            if close_after:
                client.close()


class EmailAdapter:
    """Entrega de notificaciones/recordatorios por correo electrónico (SMTP o consola en desarrollo)."""

    def enviar(self, correo: str, titulo: str, cuerpo: str, enlace: Optional[str] = None) -> DeliveryResult:
        if not correo or "@" not in correo:
            return DeliveryResult(exito=False, codigo="DESTINO_INVALIDO", detalle="Correo destinatario inválido")

        contenido = f"{cuerpo}\n"
        if enlace:
            contenido += f"\nAccede directamente desde la plataforma: {enlace}\n"
        contenido += "\nHospital San Juan de Dios - Plataforma de Telemedicina"

        if not settings.EMAIL_ENABLED:
            logger.info("[DEV EMAIL CU20] Para=%s | Asunto=%s | Cuerpo=%s", correo, titulo, cuerpo)
            return DeliveryResult(exito=True, codigo="ACEPTADO", mensaje_id=f"dev_mail_{uuid.uuid4().hex[:10]}")

        msg = EmailMessage()
        msg["Subject"] = f"{titulo} - Hospital San Juan de Dios"
        sender_addr = settings.SMTP_USER if settings.SMTP_USER else settings.SMTP_FROM
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{sender_addr}>"
        msg["To"] = correo
        msg.set_content(contenido)

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            return DeliveryResult(exito=True, codigo="ACEPTADO", mensaje_id=f"smtp_{uuid.uuid4().hex[:10]}")
        except Exception as exc:
            logger.warning("[SMTP ERROR CU20] Destino=%s error=%s", correo, str(exc)[:120])
            return DeliveryResult(
                exito=False,
                codigo="ERROR_PROVEEDOR",
                reintentable=True,
                detalle=str(exc)[:180],
            )


class SmsAdapter:
    """Entrega de recordatorios por SMS/mensajería reutilizando el puerto `app.core.sms`."""

    def enviar(self, telefono: str, titulo: str, cuerpo: str) -> DeliveryResult:
        if not telefono or len(telefono.strip()) < 6:
            return DeliveryResult(exito=False, codigo="DESTINO_INVALIDO", detalle="Teléfono destinatario inválido")

        mensaje = f"{titulo}: {cuerpo}"
        try:
            provider = get_sms_provider()
            provider.send(telefono.strip(), mensaje)
            return DeliveryResult(exito=True, codigo="ACEPTADO", mensaje_id=f"sms_{uuid.uuid4().hex[:10]}")
        except Exception as exc:
            logger.warning("[SMS ERROR CU20] Destino=%s error=%s", telefono, str(exc)[:120])
            return DeliveryResult(
                exito=False,
                codigo="ERROR_PROVEEDOR",
                reintentable=True,
                detalle=str(exc)[:180],
            )
