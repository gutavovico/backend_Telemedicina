"""Módulo CU20: Notificaciones y Recordatorios Multicanal (Push Web/FCM, Email, SMS)."""

from app.modules.communications.notificaciones.models import (
    DispositivoAutorizado,
    EventoOutbox,
    Notificacion,
)

__all__ = ["DispositivoAutorizado", "EventoOutbox", "Notificacion"]
