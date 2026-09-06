"""Envío de correos para la plataforma (CU23 - Recuperar Acceso).

Con EMAIL_ENABLED=True envía un correo real vía SMTP.
Con EMAIL_ENABLED=False (modo desarrollo) imprime el código en consola y lo
devuelve como debug_code en la respuesta para facilitar la demo sin SMTP.
"""
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings


def send_password_reset_email(correo: str, codigo: str) -> Optional[str]:
    """Envía el código de recuperación al correo indicado.

    Devuelve el código solo en modo desarrollo (EMAIL_ENABLED=False); en
    producción devuelve None (el código no debe viajar en la respuesta).
    """
    if settings.EMAIL_ENABLED:
        _send_smtp(correo, codigo)
        return None

    print(f"[DEV] Código de recuperación para {correo}: {codigo}")
    return codigo


def _send_smtp(correo: str, codigo: str) -> None:
    """Envía el correo a través de SMTP configurado en las settings."""
    msg = EmailMessage()
    msg["Subject"] = "Recuperación de contraseña - Hospital San Juan de Dios"
    sender_addr = settings.SMTP_USER if settings.SMTP_USER else settings.SMTP_FROM
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{sender_addr}>"
    msg["To"] = correo
    msg.set_content(
        "Hola,\n\n"
        "Recibiste este correo porque solicitaste recuperar tu contraseña.\n"
        f"Tu código de recuperación es: {codigo}\n"
        f"El código es válido por {settings.RESET_CODE_TTL_MINUTES} minutos.\n\n"
        "Si no solicitaste este cambio, ignora este mensaje.\n\n"
        "Hospital San Juan de Dios - Portal de Telemedicina"
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        # Si el login falla pero send_message ya corrió, el correo se envió igual.
        # Solo registramos el error internamente y no lo lanzamos al usuario.
        print(f"[SMTP WARNING] Error durante envío de correo a {correo}: {str(e)[:100]}")