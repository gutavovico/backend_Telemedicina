"""Envío de SMS para la plataforma (CU23 - Recuperar Acceso, canal SMS).

Replica el diseño ya usado por `app/core/email.py`: un puerto con dos
adaptadores seleccionables por configuración.

- `SMS_PROVIDER=console` (por defecto): imprime el código y lo devuelve para
  inspección en desarrollo, sin llamar a ningún tercero.
- `SMS_PROVIDER=twilio`: envía el mensaje real. El SDK se importa de forma
  diferida para que el proyecto arranque sin credenciales y sin la dependencia
  instalada.

Ninguna credencial se lee del código: todas vienen de variables de entorno.
"""
import logging
from typing import Optional, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class SmsProvider(Protocol):
    """Contrato mínimo de un proveedor de SMS."""

    def send(self, telefono: str, mensaje: str) -> None:
        ...


class ConsoleSmsProvider:
    """Proveedor de desarrollo: imprime el mensaje y no sale a la red."""

    def send(self, telefono: str, mensaje: str) -> None:
        print(f"[DEV SMS] Para {telefono}: {mensaje}")


class TwilioSmsProvider:
    """Proveedor real. El SDK se importa dentro del método, no al importar el
    módulo, para que `console` funcione aunque `twilio` no esté instalado."""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            from twilio.rest import Client  # import diferido

            self._client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        return self._client

    def send(self, telefono: str, mensaje: str) -> None:
        client = self._get_client()
        client.messages.create(
            body=mensaje,
            from_=settings.TWILIO_FROM_NUMBER,
            to=telefono,
        )


def get_sms_provider() -> SmsProvider:
    """Resuelve el proveedor configurado."""
    if settings.SMS_PROVIDER.lower() == "twilio":
        return TwilioSmsProvider()
    return ConsoleSmsProvider()


def send_password_reset_sms(telefono: str, codigo: str) -> Optional[str]:
    """Envía el código de recuperación por SMS.

    Devuelve el código solo en modo `console` (desarrollo); con Twilio devuelve
    None porque el código no debe viajar en la respuesta. Nunca propaga al
    llamante el fallo del proveedor: el endpoint responde siempre el mensaje
    genérico para no filtrar información del usuario (escenario de la delta).
    """
    mensaje = (
        "Hospital San Juan de Dios: tu codigo de recuperacion es "
        f"{codigo}. Válido por {settings.RESET_CODE_TTL_MINUTES} minutos."
    )

    proveedor = get_sms_provider()
    try:
        proveedor.send(telefono, mensaje)
    except Exception as exc:  # noqa: BLE001 - el fallo no debe romper el flujo
        # Se registra recortado para no volcar credenciales en el log.
        logger.warning("Fallo el envío de SMS a %s: %s", telefono, str(exc)[:100])
        return None

    if settings.SMS_PROVIDER.lower() == "console":
        print(f"[DEV] Codigo de recuperacion SMS para {telefono}: {codigo}")
        return codigo

    return None
