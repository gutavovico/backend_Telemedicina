"""Router HTTP de CU19 - Procesar Pagos de Servicios Médicos."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.payments import service
from app.modules.payments.schemas import (
    CheckoutCreate,
    CheckoutResponse,
    CitaPendienteListResponse,
    ComprobanteResponse,
    PagoListResponse,
    PagoResponse,
)

router = APIRouter(prefix="/pagos", tags=["Pagos y Comprobantes (CU19)"])


def pago_error_handler(request: Request, exc: service.PagoError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _raise(exc: service.PagoError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# --------------------------------------------------------------------------- #
# Endpoints estáticos (deben declararse antes de /{id_pago})
# --------------------------------------------------------------------------- #
@router.get(
    "/estado-pasarela",
    summary="Estado de configuración de la pasarela de pagos",
)
def estado_pasarela():
    habilitada = service.stripe_habilitado()
    return {
        "habilitada": habilitada,
        "modo": "STRIPE_SANDBOX" if habilitada else "SIMULADO",
        "moneda": "BOB",
        "pasarela": "STRIPE",
    }


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una sesión de pago (Stripe Checkout) para una cita",
)
def crear_checkout(
    datos: CheckoutCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        return service.crear_checkout(
            db,
            current_user,
            id_cita=datos.id_cita,
            canal=datos.canal,
            metodo_pago=datos.metodo_pago,
        )
    except service.PagoError as exc:
        _raise(exc)


@router.get(
    "/pendientes",
    response_model=CitaPendienteListResponse,
    summary="Listar citas/teleconsultas pendientes de pago del usuario",
)
def listar_pendientes(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.listar_citas_pendientes(db, current_user)


@router.get(
    "/mis-pagos",
    response_model=PagoListResponse,
    summary="Listar los pagos y comprobantes del usuario autenticado",
)
def listar_pagos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return service.listar_pagos(db, current_user)


@router.get(
    "/retorno",
    response_class=HTMLResponse,
    include_in_schema=False,
    summary="Página de retorno del Checkout en móvil",
)
def pagina_retorno(estado: str = "exito", pago: str | None = None):
    if estado == "cancelado":
        titulo = "Pago cancelado"
        mensaje = "No se completó el pago. Puedes intentarlo nuevamente desde la aplicación."
        color = "#b45309"
    else:
        titulo = "Pago completado"
        mensaje = "Tu pago fue registrado. Vuelve a la aplicación para descargar tu comprobante."
        color = "#15803d"
    referencia = f"<p>Pago N° <strong>{pago}</strong></p>" if pago else ""
    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo}</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;background:#f8fafc;margin:0;padding:32px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:32px;text-align:center;box-shadow:0 10px 30px rgba(15,23,42,.08);">
<div style="font-size:48px;color:{color};">&#10003;</div>
<h1 style="color:{color};font-size:22px;">{titulo}</h1>
<p style="color:#334155;">{mensaje}</p>{referencia}
<p style="color:#64748b;font-size:12px;margin-top:24px;">Hospital San Juan de Dios - Telemedicina</p>
</div></body></html>"""
    return HTMLResponse(content=html)


# --------------------------------------------------------------------------- #
# Modo demostración (sin credenciales Stripe)
# --------------------------------------------------------------------------- #
@router.get(
    "/simulado/{qr_token}",
    response_class=HTMLResponse,
    include_in_schema=False,
    summary="Página de pago simulado para demo local",
)
def pagina_simulada(qr_token: str):
    if service.stripe_habilitado():
        raise HTTPException(
            status_code=409,
            detail="La pasarela real está habilitada; use Stripe Checkout",
        )
    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pago simulado - Telemedicina</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;background:#f8fafc;margin:0;padding:32px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:32px;text-align:center;box-shadow:0 10px 30px rgba(15,23,42,.08);">
<h1 style="color:#002d62;font-size:22px;">Pasarela en modo demostración</h1>
<p style="color:#334155;">No se han configurado credenciales de Stripe. Confirma el pago simulado para emitir el comprobante.</p>
<form method="post" action="/pagos/simulado/{qr_token}/confirmar">
<button type="submit" style="background:#002d62;color:#fff;border:0;border-radius:10px;padding:12px 22px;font-size:15px;cursor:pointer;">
Confirmar pago simulado</button>
</form>
<p style="color:#64748b;font-size:12px;margin-top:24px;">Hospital San Juan de Dios - Telemedicina</p>
</div></body></html>"""
    return HTMLResponse(content=html)


@router.post(
    "/simulado/{qr_token}/confirmar",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def confirmar_simulado(qr_token: str, db: Session = Depends(get_db)):
    try:
        pago = service.confirmar_simulado_por_token(db, qr_token)
    except service.PagoError as exc:
        _raise(exc)
    numero = pago.comprobante.numero_comprobante if pago.comprobante else "-"
    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pago registrado</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;background:#f8fafc;margin:0;padding:32px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:32px;text-align:center;box-shadow:0 10px 30px rgba(15,23,42,.08);">
<div style="font-size:48px;color:#15803d;">&#10003;</div>
<h1 style="color:#15803d;font-size:22px;">Pago registrado</h1>
<p style="color:#334155;">Comprobante <strong>{numero}</strong> emitido correctamente.</p>
<p style="color:#334155;">Vuelve a la aplicación para descargar tu comprobante en PDF.</p>
</div></body></html>"""
    return HTMLResponse(content=html)


@router.get(
    "/qr/{qr_token}",
    include_in_schema=False,
    summary="Redirección corta usada por el código QR de pago",
)
def redirigir_qr(qr_token: str, db: Session = Depends(get_db)):
    try:
        url = service.resolver_qr_token(db, qr_token)
    except service.PagoError as exc:
        _raise(exc)
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post(
    "/webhook/stripe",
    summary="Webhook de confirmación de pagos de Stripe",
)
async def webhook_stripe(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    try:
        return service.procesar_webhook(db, payload, signature)
    except service.PagoError as exc:
        _raise(exc)


# --------------------------------------------------------------------------- #
# Endpoints por pago
# --------------------------------------------------------------------------- #
@router.get(
    "/{id_pago}",
    response_model=PagoResponse,
    summary="Obtener el detalle de un pago",
)
def obtener_pago(
    id_pago: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        return service.obtener_pago(db, current_user, id_pago)
    except service.PagoError as exc:
        _raise(exc)


@router.post(
    "/{id_pago}/sincronizar",
    response_model=PagoResponse,
    summary="Sincronizar el estado del pago con Stripe",
)
def sincronizar_pago(
    id_pago: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        return service.sincronizar_pago(db, current_user, id_pago)
    except service.PagoError as exc:
        _raise(exc)


@router.post(
    "/{id_pago}/simular-pago",
    response_model=PagoResponse,
    summary="Confirmar un pago en modo demostración",
)
def simular_pago(
    id_pago: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        return service.simular_pago(db, current_user, id_pago)
    except service.PagoError as exc:
        _raise(exc)


@router.get(
    "/{id_pago}/comprobante",
    response_model=ComprobanteResponse,
    summary="Obtener el comprobante digital de un pago",
)
def obtener_comprobante(
    id_pago: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        comprobante = service.obtener_comprobante(db, current_user, id_pago)
        return ComprobanteResponse.model_validate(comprobante)
    except service.PagoError as exc:
        _raise(exc)


@router.get(
    "/{id_pago}/comprobante/pdf",
    summary="Descargar el comprobante digital en PDF",
    response_class=Response,
)
def descargar_comprobante_pdf(
    id_pago: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        comprobante = service.obtener_comprobante(db, current_user, id_pago)
        pago = service._obtener_pago(db, id_pago)
        contenido = None
        if comprobante.archivo_url:
            contenido = service.storage.read(comprobante.archivo_url)
        if not contenido:
            clinica = service._clinica_de_pago(db, pago)
            contenido = service.build_comprobante_pdf(
                pago, comprobante, pago.cita, clinica
            )
    except service.PagoError as exc:
        _raise(exc)

    nombre = f"{comprobante.numero_comprobante}.pdf"
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get(
    "/{id_pago}/qr",
    summary="Imagen PNG del código QR para pagar la cita",
    response_class=Response,
)
def obtener_qr_pago(
    id_pago: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        pago = service._obtener_pago(db, id_pago)
        service._autorizar_pago(db, current_user, pago)
    except service.PagoError as exc:
        _raise(exc)

    if not pago.qr_token:
        raise HTTPException(status_code=404, detail="El pago no tiene código QR")
    payload = f"{(settings.PAYMENT_PUBLIC_BASE_URL or '').rstrip('/')}/pagos/qr/{pago.qr_token}"
    try:
        png = service.build_qr_png(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No fue posible generar el QR: {exc}")
    return Response(content=png, media_type="image/png")
