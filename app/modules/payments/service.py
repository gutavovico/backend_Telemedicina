"""Servicio de negocio para CU19 - Procesar Pagos de Servicios Médicos.

Flujo:
1. El paciente elige una cita/teleconsulta pendiente.
2. El backend crea una orden local (`pagos`) y una sesión de Stripe Checkout.
3. El paciente paga con tarjeta en Stripe o escanea el QR (que apunta a un
   redirector corto del backend hacia la misma sesión de Checkout).
4. El webhook de Stripe (o la sincronización manual) confirma el pago y el
   sistema emite el comprobante digital en PDF.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import logging
import secrets
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.modules.appointments.models import Cita, Medico, ServicioMedico
from app.modules.auth.models import Clinica, Usuario
from app.modules.medical_records.clinical_documents.storage import storage
from app.modules.medical_records.models import Paciente
from app.modules.notificaciones.service import notificar_pago_confirmado
from app.modules.payments.models import Comprobante, Pago
from app.modules.payments.schemas import (
    CheckoutResponse,
    CitaPendienteListResponse,
    CitaPendientePago,
    ComprobanteResponse,
    PagoListResponse,
    PagoResponse,
)

logger = logging.getLogger(__name__)

ESTADOS_PAGO_VALIDOS = {"PENDIENTE", "PAGADO", "FALLIDO", "CANCELADO", "REEMBOLSADO"}
ROLES_STAFF = {"ADMIN", "ADMINISTRADOR", "ADMINISTRACION", "MEDICO", "RECEPCION", "RECEPCIONISTA"}


class PagoError(Exception):
    """Error de negocio con código HTTP asociado."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# --------------------------------------------------------------------------- #
# Utilidades de autorización y formato
# --------------------------------------------------------------------------- #
def _rol_nombre(usuario: Usuario) -> str:
    try:
        if isinstance(usuario.rol, str):
            return usuario.rol.strip().upper()
        if getattr(usuario, "rol_rel", None) and getattr(usuario.rol_rel, "nombre", None):
            return usuario.rol_rel.nombre.strip().upper()
    except Exception:
        pass
    return ""


def _es_staff(usuario: Usuario) -> bool:
    return _rol_nombre(usuario) in ROLES_STAFF or usuario.id_rol == 1


def _paciente_de_usuario(db: Session, usuario: Usuario) -> Optional[Paciente]:
    return db.query(Paciente).filter(Paciente.id_usuario == usuario.id_usuario).first()


def _cita_con_relaciones(db: Session, id_cita: int) -> Optional[Cita]:
    return (
        db.query(Cita)
        .options(
            joinedload(Cita.paciente),
            joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Cita.especialidad),
        )
        .filter(Cita.id_cita == id_cita)
        .first()
    )


def _autorizar_cita(db: Session, usuario: Usuario, cita: Cita) -> None:
    """Un paciente solo puede operar sus propias citas; el staff, las de su clínica."""
    if _es_staff(usuario):
        if (
            cita.id_clinica is not None
            and usuario.id_clinica is not None
            and cita.id_clinica != usuario.id_clinica
        ):
            raise PagoError(404, "Cita no encontrada")
        return

    paciente = _paciente_de_usuario(db, usuario)
    if not paciente or cita.id_paciente != paciente.id_paciente:
        raise PagoError(403, "No tienes permiso para pagar esta cita")


def _autorizar_pago(db: Session, usuario: Usuario, pago: Pago) -> None:
    if _es_staff(usuario):
        if (
            pago.id_clinica is not None
            and usuario.id_clinica is not None
            and pago.id_clinica != usuario.id_clinica
        ):
            raise PagoError(404, "Pago no encontrado")
        return
    if pago.id_usuario != usuario.id_usuario:
        raise PagoError(403, "No tienes permiso para acceder a este pago")


def _nombre_medico(cita: Cita) -> str:
    medico = getattr(cita, "medico", None)
    if not medico:
        return f"Médico #{cita.id_medico}"
    usuario = getattr(medico, "usuario", None)
    if usuario:
        nombre = f"{usuario.nombres or ''} {usuario.apellidos or ''}".strip()
        if nombre.lower().startswith(("dr.", "dra.", "dr(a).")):
            return nombre
        return f"Dr. {nombre}".strip()
    return f"Médico Matrícula: {getattr(medico, 'matricula_profesional', cita.id_medico)}"


def _especialidad_nombre(cita: Cita) -> str:
    if getattr(cita, "especialidad", None):
        return cita.especialidad.nombre
    medico = getattr(cita, "medico", None)
    if medico and getattr(medico, "especialidades", None):
        for relacion in medico.especialidades:
            if getattr(relacion, "especialidad", None):
                return relacion.especialidad.nombre
    return "Medicina General"


def _monto_cita(db: Session, cita: Cita) -> Decimal:
    """El costo se toma del servicio médico asociado; si no existe o es cero,
    se usa el monto por defecto (Stripe no permite cobrar 0 en Checkout)."""
    if cita.id_servicio:
        servicio = (
            db.query(ServicioMedico)
            .filter(ServicioMedico.id_servicio == cita.id_servicio)
            .first()
        )
        if servicio and servicio.costo is not None:
            costo = Decimal(str(servicio.costo)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if costo > 0:
                return costo
    return Decimal(str(settings.PAYMENT_DEFAULT_AMOUNT)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _comprobante_response(comprobante: Optional[Comprobante]) -> Optional[ComprobanteResponse]:
    if not comprobante:
        return None
    return ComprobanteResponse.model_validate(comprobante)


def _pago_response(pago: Pago) -> PagoResponse:
    cita = getattr(pago, "cita", None)
    return PagoResponse(
        id_pago=pago.id_pago,
        id_usuario=pago.id_usuario,
        id_cita=pago.id_cita,
        monto=pago.monto,
        moneda=pago.moneda or "BOB",
        metodo_pago=pago.metodo_pago,
        pasarela=pago.pasarela,
        referencia_transaccion=pago.referencia_transaccion,
        fecha_pago=pago.fecha_pago,
        estado=pago.estado,
        url_checkout=pago.url_checkout,
        expira_en=pago.expira_en,
        created_at=pago.created_at,
        cita_fecha=getattr(cita, "fecha_cita", None),
        cita_hora=getattr(cita, "hora_inicio", None),
        medico_nombre=_nombre_medico(cita) if cita else None,
        especialidad_nombre=_especialidad_nombre(cita) if cita else None,
        tipo_consulta=getattr(cita, "tipo_consulta", None) if cita else None,
        comprobante=_comprobante_response(getattr(pago, "comprobante", None)),
    )


# --------------------------------------------------------------------------- #
# Configuración / Stripe
# --------------------------------------------------------------------------- #
def _stripe_secret() -> str:
    try:
        return settings.STRIPE_SECRET_KEY.get_secret_value().strip()
    except Exception:
        return str(settings.STRIPE_SECRET_KEY or "").strip()


def _stripe_webhook_secret() -> str:
    try:
        return settings.STRIPE_WEBHOOK_SECRET.get_secret_value().strip()
    except Exception:
        return str(settings.STRIPE_WEBHOOK_SECRET or "").strip()


def stripe_habilitado() -> bool:
    return bool(_stripe_secret())


def _public_base() -> str:
    return (settings.PAYMENT_PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")


def _with_query(url: str, params: Dict[str, str]) -> str:
    if not params:
        return url
    separador = "&" if "?" in url else "?"
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{url}{separador}{query}"


def _urls_retorno(pago: Pago, canal: str) -> Tuple[str, str]:
    if canal == "MOVIL":
        success = _with_query(
            settings.PAYMENT_MOBILE_SUCCESS_URL, {"pago": str(pago.id_pago)}
        )
        cancel = _with_query(
            settings.PAYMENT_MOBILE_CANCEL_URL, {"pago": str(pago.id_pago)}
        )
        return success, cancel

    success = _with_query(
        settings.PAYMENT_WEB_SUCCESS_URL,
        {"pago": str(pago.id_pago), "session_id": "{CHECKOUT_SESSION_ID}"},
    )
    cancel = _with_query(settings.PAYMENT_WEB_CANCEL_URL, {"pago": str(pago.id_pago)})
    return success, cancel


def _stripe_request(method: str, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    secret = _stripe_secret()
    if not secret:
        raise PagoError(503, "Stripe no está configurado")

    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {k: str(v) for k, v in (data or {}).items()}
    url = f"{settings.STRIPE_API_BASE_URL.rstrip('/')}{path}"

    try:
        with httpx.Client(timeout=settings.STRIPE_TIMEOUT_SECONDS) as client:
            if method.upper() == "GET":
                response = client.get(url, headers=headers)
            else:
                response = client.post(url, headers=headers, data=payload)
    except httpx.HTTPError as exc:
        logger.error("Error de red con Stripe: %s", exc)
        raise PagoError(502, "No fue posible comunicarse con la pasarela de pagos") from exc

    try:
        body = response.json()
    except Exception:
        body = {}

    if response.status_code >= 400:
        mensaje = (body.get("error") or {}).get("message") or "Error de Stripe"
        logger.error("Stripe respondió %s: %s", response.status_code, mensaje)
        raise PagoError(502, f"Stripe: {mensaje}")

    return body


def _crear_sesion_stripe(pago: Pago, cita: Cita, canal: str) -> Dict[str, Any]:
    success_url, cancel_url = _urls_retorno(pago, canal)
    descripcion = f"Cita #{cita.id_cita} - {cita.fecha_cita or ''} {cita.hora_inicio or ''}".strip()
    amount = int((Decimal(pago.monto) * 100).to_integral_value(rounding=ROUND_HALF_UP))

    data: Dict[str, Any] = {
        "mode": "payment",
        # Stripe gestiona los métodos de pago dinámicamente desde el Dashboard;
        # enviar `payment_method_types` en Checkout ahora devuelve error 400.
        "line_items[0][quantity]": 1,
        "line_items[0][price_data][currency]": (settings.STRIPE_CURRENCY or "bob").lower(),
        "line_items[0][price_data][unit_amount]": amount,
        "line_items[0][price_data][product_data][name]": (
            f"Consulta médica - {_especialidad_nombre(cita)}"
        ),
        "line_items[0][price_data][product_data][description]": descripcion,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": f"pago-{pago.id_pago}",
        "locale": "es",
        "metadata[id_pago]": pago.id_pago,
        "metadata[id_cita]": cita.id_cita,
        "metadata[id_usuario]": pago.id_usuario,
    }
    return _stripe_request(
        "POST",
        "/v1/checkout/sessions",
        data=data,
    )


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
def crear_checkout(db: Session, usuario: Usuario, id_cita: int, canal: str = "WEB", metodo_pago: str = "TARJETA") -> CheckoutResponse:
    cita = _cita_con_relaciones(db, id_cita)
    if not cita:
        raise PagoError(404, "Cita no encontrada")
    _autorizar_cita(db, usuario, cita)

    if (cita.estado or "").upper() == "CANCELADA":
        raise PagoError(409, "No se puede pagar una cita cancelada")

    # Si ya existe un pago aprobado, se devuelve el comprobante en lugar de cobrar dos veces.
    pago_aprobado = (
        db.query(Pago)
        .filter(Pago.id_cita == cita.id_cita, Pago.estado == "PAGADO")
        .order_by(Pago.id_pago.desc())
        .first()
    )
    if pago_aprobado:
        return _checkout_response(db, pago_aprobado, simulado=not stripe_habilitado())

    # Reutiliza una sesión pendiente vigente del mismo usuario.
    ahora = datetime.utcnow()
    pago_pendiente = (
        db.query(Pago)
        .filter(
            Pago.id_cita == cita.id_cita,
            Pago.id_usuario == usuario.id_usuario,
            Pago.estado == "PENDIENTE",
            Pago.url_checkout.isnot(None),
        )
        .order_by(Pago.id_pago.desc())
        .first()
    )
    if pago_pendiente and (pago_pendiente.expira_en is None or pago_pendiente.expira_en > ahora):
        return _checkout_response(db, pago_pendiente, simulado=not stripe_habilitado())

    monto = _monto_cita(db, cita)
    pago = Pago(
        id_usuario=usuario.id_usuario,
        id_cita=cita.id_cita,
        id_clinica=cita.id_clinica or usuario.id_clinica,
        monto=monto,
        moneda="BOB",
        metodo_pago=metodo_pago,
        pasarela="STRIPE",
        estado="PENDIENTE",
        qr_token=secrets.token_urlsafe(9),
        expira_en=ahora + timedelta(minutes=settings.PAYMENT_SESSION_TTL_MINUTES),
    )
    db.add(pago)
    db.commit()
    db.refresh(pago)

    if stripe_habilitado():
        try:
            sesion = _crear_sesion_stripe(pago, cita, canal)
        except PagoError:
            pago.estado = "FALLIDO"
            db.commit()
            raise
        pago.stripe_session_id = sesion.get("id")
        pago.stripe_payment_intent_id = sesion.get("payment_intent")
        pago.url_checkout = sesion.get("url")
        expira = sesion.get("expires_at")
        if expira:
            try:
                pago.expira_en = datetime.utcfromtimestamp(int(expira))
            except Exception:
                pass
    else:
        # Modo demostración: permite recorrer el flujo sin credenciales reales.
        pago.url_checkout = f"{_public_base()}/pagos/simulado/{pago.qr_token}"

    db.commit()
    db.refresh(pago)
    return _checkout_response(db, pago, simulado=not stripe_habilitado())


def _checkout_response(db: Session, pago: Pago, simulado: bool) -> CheckoutResponse:
    # Asegura relaciones cargadas para la respuesta.
    if getattr(pago, "cita", None) is None and pago.id_cita:
        pago.cita = _cita_con_relaciones(db, pago.id_cita)
    base = _pago_response(pago)
    payload = f"{_public_base()}/pagos/qr/{pago.qr_token}" if pago.qr_token else None
    return CheckoutResponse(
        **base.model_dump(),
        qr_url=f"{_public_base()}/pagos/{pago.id_pago}/qr",
        qr_payload=payload,
        simulado=simulado,
    )


# --------------------------------------------------------------------------- #
# Confirmación / sincronización
# --------------------------------------------------------------------------- #
def _finalizar_pago(db: Session, pago: Pago, session_payload: Optional[Dict[str, Any]] = None) -> Pago:
    """Marca el pago como PAGADO y emite el comprobante de forma idempotente."""
    if (pago.estado or "").upper() == "PAGADO" and pago.comprobante:
        return pago

    if session_payload:
        pago.stripe_session_id = session_payload.get("id") or pago.stripe_session_id
        pago.stripe_payment_intent_id = (
            session_payload.get("payment_intent") or pago.stripe_payment_intent_id
        )
        pago.referencia_transaccion = (
            session_payload.get("payment_intent")
            or session_payload.get("id")
            or pago.referencia_transaccion
        )

    if not pago.referencia_transaccion:
        pago.referencia_transaccion = pago.stripe_session_id or f"SIM-{pago.id_pago}"

    pago.estado = "PAGADO"
    pago.fecha_pago = datetime.utcnow()

    cita = getattr(pago, "cita", None) or (db.query(Cita).filter(Cita.id_cita == pago.id_cita).first() if pago.id_cita else None)
    if cita and (cita.estado or "").upper() == "PENDIENTE":
        cita.estado = "CONFIRMADA"

    clinica = _clinica_de_pago(db, pago)

    if not pago.comprobante:
        numero = f"REC-{datetime.utcnow().strftime('%Y%m%d')}-{pago.id_pago:06d}"
        comprobante = Comprobante(
            id_pago=pago.id_pago,
            numero_comprobante=numero,
            tipo_comprobante="RECIBO",
            fecha_emision=datetime.utcnow(),
            estado="EMITIDO",
        )
        db.add(comprobante)
        db.flush()

        try:
            pdf_bytes = build_comprobante_pdf(pago, comprobante, cita, clinica)
            object_key, _ = storage.store(
                f"comprobante_{numero}.pdf", pdf_bytes, "application/pdf"
            )
            comprobante.archivo_url = object_key
        except Exception as exc:  # El pago no debe fallar por un problema de PDF.
            logger.exception("No fue posible generar el comprobante %s: %s", numero, exc)

    db.commit()
    db.refresh(pago)
    # CU19: aviso push solo a la app Android. Un fallo del proveedor no revierte
    # el pago porque el servicio captura cualquier excepción.
    notificar_pago_confirmado(db, pago)
    return pago


def sincronizar_pago(db: Session, usuario: Usuario, id_pago: int) -> PagoResponse:
    pago = _obtener_pago(db, id_pago)
    _autorizar_pago(db, usuario, pago)

    if (pago.estado or "").upper() == "PAGADO":
        return _pago_response(pago)

    if pago.stripe_session_id and stripe_habilitado():
        sesion = _stripe_request("GET", f"/v1/checkout/sessions/{pago.stripe_session_id}")
        estado = (sesion.get("status") or "").lower()
        pagado = (sesion.get("payment_status") or "").lower() == "paid"
        if estado == "complete" and pagado:
            pago = _finalizar_pago(db, pago, sesion)
        elif estado == "expired":
            pago.estado = "CANCELADO"
            db.commit()
        else:
            db.refresh(pago)
    else:
        db.refresh(pago)

    return _pago_response(pago)


def simular_pago(db: Session, usuario: Usuario, id_pago: int) -> PagoResponse:
    """Confirma un pago en modo demostración (sin credenciales Stripe)."""
    pago = _obtener_pago(db, id_pago)
    _autorizar_pago(db, usuario, pago)
    if stripe_habilitado():
        raise PagoError(409, "La pasarela real está habilitada; use Stripe Checkout")
    if (pago.estado or "").upper() == "PAGADO":
        return _pago_response(pago)
    pago.metodo_pago = pago.metodo_pago or "TARJETA"
    pago = _finalizar_pago(db, pago, {"id": f"sim_{pago.id_pago}", "payment_intent": f"sim_pi_{pago.id_pago}"})
    return _pago_response(pago)


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
def verificar_firma_stripe(payload: bytes, signature_header: str, secret: str) -> None:
    """Valida la firma `Stripe-Signature` (t=...,v1=...)."""
    if not secret:
        raise PagoError(400, "Webhook de Stripe no configurado")

    partes: Dict[str, List[str]] = {}
    for item in (signature_header or "").split(","):
        if "=" not in item:
            continue
        clave, valor = item.split("=", 1)
        partes.setdefault(clave.strip(), []).append(valor.strip())

    try:
        timestamp = int(partes.get("t", ["0"])[0])
    except (TypeError, ValueError):
        raise PagoError(400, "Cabecera de firma inválida")

    if abs(time.time() - timestamp) > settings.STRIPE_WEBHOOK_TOLERANCE_SECONDS:
        raise PagoError(400, "Firma de webhook expirada")

    firmado = f"{timestamp}.".encode("utf-8") + payload
    esperado = hmac.new(secret.encode("utf-8"), firmado, hashlib.sha256).hexdigest()

    recibidas = partes.get("v1", [])
    if not any(hmac.compare_digest(esperado, recibida) for recibida in recibidas):
        raise PagoError(400, "Firma de webhook inválida")


def procesar_webhook(db: Session, payload: bytes, signature_header: str) -> Dict[str, Any]:
    secret = _stripe_webhook_secret()
    verificar_firma_stripe(payload, signature_header, secret)

    import json

    try:
        evento = json.loads(payload.decode("utf-8"))
    except Exception:
        raise PagoError(400, "Cuerpo de webhook inválido")

    tipo = evento.get("type") or ""
    if tipo not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return {"received": True, "ignored": tipo}

    sesion = (evento.get("data") or {}).get("object") or {}
    metadata = sesion.get("metadata") or {}
    id_pago = metadata.get("id_pago") or sesion.get("client_reference_id", "").replace("pago-", "")

    pago = None
    if id_pago:
        try:
            pago = db.query(Pago).filter(Pago.id_pago == int(id_pago)).first()
        except (TypeError, ValueError):
            pago = None
    if pago is None and sesion.get("id"):
        pago = db.query(Pago).filter(Pago.stripe_session_id == sesion.get("id")).first()
    if pago is None:
        logger.warning("Webhook Stripe sin pago asociado: %s", sesion.get("id"))
        return {"received": True, "pago": None}

    _finalizar_pago(db, pago, sesion)
    return {"received": True, "id_pago": pago.id_pago, "estado": pago.estado}


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #
def _clinica_de_pago(db: Session, pago: Pago) -> Optional[Clinica]:
    """Recupera la clínica emisora para los datos fiscales del comprobante."""
    if not pago.id_clinica:
        return None
    return db.query(Clinica).filter(Clinica.id_clinica == pago.id_clinica).first()


def _obtener_pago(db: Session, id_pago: int) -> Pago:
    pago = (
        db.query(Pago)
        .options(
            joinedload(Pago.cita).joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Pago.cita).joinedload(Cita.especialidad),
            joinedload(Pago.comprobante),
        )
        .filter(Pago.id_pago == id_pago)
        .first()
    )
    if not pago:
        raise PagoError(404, "Pago no encontrado")
    return pago


def obtener_pago(db: Session, usuario: Usuario, id_pago: int) -> PagoResponse:
    pago = _obtener_pago(db, id_pago)
    _autorizar_pago(db, usuario, pago)
    return _pago_response(pago)


def listar_pagos(db: Session, usuario: Usuario) -> PagoListResponse:
    query = (
        db.query(Pago)
        .options(
            joinedload(Pago.cita).joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Pago.cita).joinedload(Cita.especialidad),
            joinedload(Pago.comprobante),
        )
    )
    if _es_staff(usuario):
        if usuario.id_clinica is not None:
            query = query.filter(Pago.id_clinica == usuario.id_clinica)
    else:
        query = query.filter(Pago.id_usuario == usuario.id_usuario)

    pagos = query.order_by(Pago.id_pago.desc()).all()
    items = [_pago_response(p) for p in pagos]
    return PagoListResponse(total=len(items), items=items)


def listar_citas_pendientes(db: Session, usuario: Usuario) -> CitaPendienteListResponse:
    query = (
        db.query(Cita)
        .options(
            joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Cita.especialidad),
        )
        .filter(Cita.estado.notin_(["CANCELADA", "COMPLETADA"]))
    )

    if _es_staff(usuario):
        if usuario.id_clinica is not None:
            query = query.filter(Cita.id_clinica == usuario.id_clinica)
    else:
        paciente = _paciente_de_usuario(db, usuario)
        if not paciente:
            return CitaPendienteListResponse(total=0, items=[])
        query = query.filter(Cita.id_paciente == paciente.id_paciente)

    citas = query.order_by(Cita.fecha_cita.asc(), Cita.hora_inicio.asc()).all()
    if not citas:
        return CitaPendienteListResponse(total=0, items=[])

    ids = [c.id_cita for c in citas]
    pagos = (
        db.query(Pago)
        .filter(Pago.id_cita.in_(ids), Pago.estado.in_(["PENDIENTE", "PAGADO"]))
        .order_by(Pago.id_pago.desc())
        .all()
    )
    por_cita: Dict[int, Pago] = {}
    for pago in pagos:
        # Prioriza el pago aprobado; si no, conserva el pendiente más reciente.
        actual = por_cita.get(pago.id_cita)
        if actual is None or pago.estado == "PAGADO":
            por_cita[pago.id_cita] = pago

    items: List[CitaPendientePago] = []
    for cita in citas:
        pago = por_cita.get(cita.id_cita)
        if pago and pago.estado == "PAGADO":
            continue
        items.append(
            CitaPendientePago(
                id_cita=cita.id_cita,
                fecha_cita=cita.fecha_cita,
                hora_inicio=cita.hora_inicio,
                hora_fin=cita.hora_fin,
                medico_nombre=_nombre_medico(cita),
                especialidad_nombre=_especialidad_nombre(cita),
                tipo_consulta=cita.tipo_consulta,
                estado_cita=cita.estado,
                monto=_monto_cita(db, cita),
                moneda="BOB",
                estado_pago=pago.estado if pago else None,
                id_pago=pago.id_pago if pago else None,
            )
        )
    return CitaPendienteListResponse(total=len(items), items=items)


def obtener_comprobante(db: Session, usuario: Usuario, id_pago: int) -> Comprobante:
    pago = _obtener_pago(db, id_pago)
    _autorizar_pago(db, usuario, pago)
    if not pago.comprobante:
        raise PagoError(404, "El pago aún no tiene comprobante emitido")
    return pago.comprobante


def resolver_qr_token(db: Session, qr_token: str) -> str:
    pago = db.query(Pago).filter(Pago.qr_token == qr_token).first()
    if not pago or not pago.url_checkout:
        raise PagoError(404, "Enlace de pago no encontrado o expirado")
    if (pago.estado or "").upper() == "PAGADO":
        raise PagoError(409, "El pago ya fue completado")
    return pago.url_checkout


def confirmar_simulado_por_token(db: Session, qr_token: str) -> Pago:
    # Con credenciales reales esta ruta queda inhabilitada: solo el webhook o
    # la sincronización con Stripe pueden confirmar un pago.
    if stripe_habilitado():
        raise PagoError(409, "La pasarela real está habilitada; use Stripe Checkout")
    pago = db.query(Pago).filter(Pago.qr_token == qr_token).first()
    if not pago:
        raise PagoError(404, "Enlace de pago no encontrado")
    if (pago.estado or "").upper() == "PAGADO":
        return pago
    return _finalizar_pago(db, pago, {"id": f"sim_{pago.id_pago}", "payment_intent": f"sim_pi_{pago.id_pago}"})


# --------------------------------------------------------------------------- #
# PDF del comprobante
# --------------------------------------------------------------------------- #
def _pdf_escape(text: Any) -> str:
    return (
        str(text if text is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_comprobante_pdf(
    pago: Pago,
    comprobante: Comprobante,
    cita: Optional[Cita] = None,
    clinica: Optional[Clinica] = None,
) -> bytes:
    """Genera el comprobante digital en PDF (reportlab).

    Incluye los datos fiscales de la clínica/hospital emisor (criterio CU19),
    los datos del paciente, el detalle del servicio y el identificador único
    de la transacción.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=f"Comprobante {comprobante.numero_comprobante}",
        author="Hospital San Juan de Dios - Telemedicina",
    )
    styles = getSampleStyleSheet()
    titulo = ParagraphStyle(
        "TituloCU19",
        parent=styles["Title"],
        fontSize=17,
        textColor=colors.HexColor("#002d62"),
        spaceAfter=4,
    )
    subtitulo = ParagraphStyle(
        "SubtituloCU19", parent=styles["Normal"], fontSize=9, textColor=colors.grey
    )
    seccion = ParagraphStyle(
        "SeccionCU19",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#002d62"),
        spaceBefore=10,
        spaceAfter=4,
    )
    normal = ParagraphStyle("NormalCU19", parent=styles["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("SmallCU19", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    paciente = getattr(cita, "paciente", None) if cita else None
    paciente_nombre = (
        f"{paciente.nombres} {paciente.apellidos}".strip() if paciente else "Paciente"
    )
    paciente_ci = getattr(paciente, "ci", "") if paciente else ""
    medico_nombre = _nombre_medico(cita) if cita else "-"
    especialidad = _especialidad_nombre(cita) if cita else "-"

    clinica_nombre = getattr(clinica, "nombre", None) or "Hospital San Juan de Dios"
    razon_social = getattr(clinica, "razon_social", None) or clinica_nombre
    nit = getattr(clinica, "nit", None) or "-"
    direccion = getattr(clinica, "direccion", None) or "-"
    telefono = getattr(clinica, "telefono", None) or "-"
    correo = getattr(clinica, "correo", None) or "-"

    story = [
        Paragraph("COMPROBANTE DE PAGO", titulo),
        Paragraph(f"{clinica_nombre} - Plataforma de Telemedicina", subtitulo),
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#002d62")),
        Spacer(1, 8),
        Paragraph(
            f"<b>Razón social:</b> {_pdf_escape(razon_social)} &nbsp;&nbsp; "
            f"<b>NIT:</b> {_pdf_escape(nit)}<br/>"
            f"<b>Dirección:</b> {_pdf_escape(direccion)} &nbsp;&nbsp; "
            f"<b>Teléfono:</b> {_pdf_escape(telefono)} &nbsp;&nbsp; "
            f"<b>Correo:</b> {_pdf_escape(correo)}",
            small,
        ),
        Spacer(1, 6),
    ]

    datos = [
        ["N° de comprobante:", comprobante.numero_comprobante, "Fecha de emisión:", comprobante.fecha_emision.strftime("%d/%m/%Y %H:%M") if comprobante.fecha_emision else "-"],
        ["Paciente:", paciente_nombre, "CI:", paciente_ci or "-"],
        ["Médico:", medico_nombre, "Especialidad:", especialidad],
        ["Cita:", f"#{pago.id_cita or '-'}", "Fecha y hora:", f"{cita.fecha_cita or '-'} {cita.hora_inicio or ''}" if cita else "-"],
        ["Modalidad:", (getattr(cita, "tipo_consulta", None) or "-") if cita else "-", "Estado:", pago.estado],
    ]
    tabla_datos = Table(datos, colWidths=[1.15 * inch, 2.15 * inch, 1.1 * inch, 2.0 * inch])
    tabla_datos.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#334155")),
                ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#334155")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(tabla_datos)

    story.append(Paragraph("Detalle del pago", seccion))
    detalle = [
        ["Concepto", "Importe"],
        [
            f"Servicio médico: {especialidad} - Cita #{pago.id_cita or '-'}",
            f"{Decimal(pago.monto):.2f} {pago.moneda or 'BOB'}",
        ],
        ["TOTAL PAGADO", f"{Decimal(pago.monto):.2f} {pago.moneda or 'BOB'}"],
    ]
    tabla_detalle = Table(detalle, colWidths=[4.6 * inch, 1.8 * inch])
    tabla_detalle.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#002d62")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8f0fe")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(tabla_detalle)

    story.append(Paragraph("Información de la transacción", seccion))
    info = [
        ["Pasarela:", pago.pasarela or "STRIPE"],
        ["Método de pago:", pago.metodo_pago or "TARJETA"],
        ["Referencia:", pago.referencia_transaccion or "-"],
        ["Fecha de pago:", pago.fecha_pago.strftime("%d/%m/%Y %H:%M") if pago.fecha_pago else "-"],
    ]
    tabla_info = Table(info, colWidths=[1.4 * inch, 5.0 * inch])
    tabla_info.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#334155")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(tabla_info)

    # QR de verificación del comprobante (opcional, no bloquea la emisión).
    try:
        payload = (
            f"{comprobante.numero_comprobante}|PAGO:{pago.id_pago}|"
            f"MONTO:{Decimal(pago.monto):.2f}{pago.moneda or 'BOB'}|"
            f"FECHA:{pago.fecha_pago.isoformat() if pago.fecha_pago else ''}"
        )
        qr_png = build_qr_png(payload, box_size=4, border=2)
        from reportlab.platypus import Image as RLImage

        story.append(Spacer(1, 8))
        story.append(RLImage(io.BytesIO(qr_png), width=0.9 * inch, height=0.9 * inch))
        story.append(Paragraph("Verificación del comprobante", small))
    except Exception:
        pass

    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#cbd5e1")))
    story.append(
        Paragraph(
            "Este comprobante es un documento digital emitido automáticamente por la "
            "plataforma de Telemedicina. Conserve el número de comprobante para "
            "cualquier consulta administrativa.",
            small,
        )
    )

    doc.build(story)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# QR
# --------------------------------------------------------------------------- #
def build_qr_png(texto: str, box_size: int = 8, border: int = 4) -> bytes:
    """Genera un PNG con el código QR del texto indicado."""
    from PIL import Image

    from app.modules.medical_records.prescriptions.qrcodegen import encode_qr_matrix

    matriz, _version = encode_qr_matrix(texto)
    n = len(matriz)
    total = (n + border * 2) * box_size
    imagen = Image.new("RGB", (total, total), "white")
    pixeles = imagen.load()

    for y, fila in enumerate(matriz):
        for x, oscuro in enumerate(fila):
            if not oscuro:
                continue
            x0 = (x + border) * box_size
            y0 = (y + border) * box_size
            for dy in range(box_size):
                for dx in range(box_size):
                    pixeles[x0 + dx, y0 + dy] = (0, 0, 0)

    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
