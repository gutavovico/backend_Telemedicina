"""Notificaciones push de CU19 (pago confirmado).

Reutiliza la infraestructura FCM de CU17: misma cuenta de servicio, mismo
cifrado de tokens y la misma tabla de dispositivos registrados por el móvil.
No crea tablas nuevas.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, lazyload

from app.modules.auth.models import Usuario
from app.modules.medical_records.tratamientos import avisos
from app.modules.medical_records.tratamientos.avisos_models import TratamientoDispositivo
from app.modules.payments.models import Pago

logger = logging.getLogger(__name__)


def _clinica_del_pago(pago: Pago) -> int | None:
    if pago.id_clinica is not None:
        return pago.id_clinica
    cita = getattr(pago, "cita", None)
    return getattr(cita, "id_clinica", None)


def _dispositivos_activos(db: Session, id_usuario: int, id_clinica: int):
    return db.execute(
        select(TratamientoDispositivo).where(
            TratamientoDispositivo.id_clinica == id_clinica,
            TratamientoDispositivo.id_usuario == id_usuario,
            TratamientoDispositivo.activo.is_(True),
        )
    ).scalars().all()


def notificar_pago_confirmado(db: Session, pago: Pago) -> int:
    """Envía un push al paciente cuando su pago queda PAGADO.

    Nunca lanza excepciones: un fallo del proveedor no debe revertir el pago.
    Devuelve cuántos dispositivos recibieron el aviso.
    """
    try:
        if not avisos.push_configurado():
            logger.info("Push CU19 omitido: proveedor no configurado (pago %s)", pago.id_pago)
            return 0

        usuario = db.execute(
            select(Usuario)
            .options(lazyload(Usuario.rol_rel))
            .where(Usuario.id_usuario == pago.id_usuario)
        ).scalar_one_or_none()
        if usuario is None or not usuario.notificaciones_push:
            return 0
        if (usuario.estado or "").upper() != "ACTIVO":
            return 0

        id_clinica = _clinica_del_pago(pago) or usuario.id_clinica
        if id_clinica is None:
            return 0

        comprobante = getattr(pago, "comprobante", None)
        numero = getattr(comprobante, "numero_comprobante", None)
        titulo = "Pago confirmado"
        mensaje = "Tu pago fue confirmado."
        if numero:
            mensaje = f"Tu pago fue confirmado. Comprobante {numero}."

        data = {
            "tipo": "PAGO_CONFIRMADO",
            "id_pago": pago.id_pago,
            "id_cita": pago.id_cita or "",
            "numero_comprobante": numero or "",
        }

        enviados = 0
        for dispositivo in _dispositivos_activos(db, pago.id_usuario, id_clinica):
            try:
                token = avisos.descifrar_token(dispositivo.token_cifrado)
                avisos.enviar_fcm_mensaje(token, titulo, mensaje, data)
                enviados += 1
            except Exception as exc:  # El pago ya está confirmado; solo se registra.
                logger.warning(
                    "No se pudo enviar push del pago %s al dispositivo %s: %s",
                    pago.id_pago,
                    dispositivo.id_dispositivo,
                    exc,
                )
        return enviados
    except Exception as exc:
        logger.exception("Error preparando push del pago %s: %s", pago.id_pago, exc)
        return 0
