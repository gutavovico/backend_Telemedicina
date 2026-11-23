"""Router FastAPI para CU20: Notificaciones y Recordatorios Multicanal."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user
from app.modules.auth.models import Usuario
from app.modules.communications.notificaciones.schemas import (
    DispositivoDTO,
    EmisionNotificacionCommand,
    MarcarTodasLeidasDTO,
    NotificacionDTO,
    NotificacionResumenDTO,
    PreferenciasNotificacionDTO,
    PreferenciasNotificacionUpdateDTO,
    ProcesarOutboxResumenDTO,
    RegistroDispositivoDTO,
    WebPushConfigDTO,
    WebPushSubscripcionDTO,
)
from app.modules.communications.notificaciones.service import NotificacionService

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones Multicanal (CU20)"])


@router.get(
    "/web-push/config",
    response_model=WebPushConfigDTO,
    summary="Obtener clave pública VAPID para suscripción Web Push PWA",
)
def obtener_config_web_push():
    pub = NotificacionService.obtener_clave_publica_vapid()
    return WebPushConfigDTO(public_key=pub, habilitado=bool(pub))


@router.post(
    "/web-push/subscripcion",
    response_model=DispositivoDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar o actualizar suscripción Web Push del navegador PWA",
)
def registrar_web_push(
    dto: WebPushSubscripcionDTO,
    usuario: Usuario = Depends(get_current_user),
    id_clinica: Optional[int] = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    srv = NotificacionService(db)
    push_token = json.dumps({"endpoint": dto.endpoint, "keys": dto.keys.model_dump()})
    reg = RegistroDispositivoDTO(
        dispositivo_id=dto.dispositivo_id or str(uuid.uuid4()),
        canal="PWA",
        push_token=push_token,
    )
    res = srv.registrar_dispositivo(usuario, reg, id_clinica=id_clinica)
    db.commit()
    return res


@router.post(
    "/dispositivos",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar dispositivo móvil (FLUTTER / CU19 FCM) o PWA para recepción de Push",
)
def registrar_dispositivo(
    payload: Dict[str, Any] = Body(...),
    usuario: Usuario = Depends(get_current_user),
    id_clinica: Optional[int] = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    # Compatibilidad con el contrato CU19 ({token, plataforma}) usado por pagos móvil
    if "token" in payload and "dispositivo_id" not in payload:
        from app.modules.notificaciones.router import (
            DispositivoCreate,
            registrar_dispositivo as registrar_dispositivo_cu19,
        )

        try:
            dto_cu19 = DispositivoCreate.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.errors(),
            ) from exc
        return registrar_dispositivo_cu19(
            payload=dto_cu19,
            db=db,
            user=usuario,
            tenant_id=id_clinica,
        )

    try:
        dto = RegistroDispositivoDTO.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    srv = NotificacionService(db)
    res = srv.registrar_dispositivo(usuario, dto, id_clinica=id_clinica)
    db.commit()
    return res


@router.get(
    "/dispositivos",
    response_model=List[DispositivoDTO],
    summary="Listar dispositivos activos registrados del usuario autenticado",
)
def listar_dispositivos(
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return NotificacionService(db).listar_dispositivos(usuario.id_usuario)


@router.delete(
    "/dispositivos/{dispositivo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revocar un dispositivo registrado (CU20 y compatibilidad CU19)",
)
def revocar_dispositivo(
    dispositivo_id: str,
    usuario: Usuario = Depends(get_current_user),
    id_clinica: Optional[int] = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    revocados = NotificacionService(db).revocar_dispositivo(
        usuario.id_usuario, dispositivo_id
    )
    if revocados == 0 and dispositivo_id.isdigit():
        from app.modules.notificaciones.router import (
            revocar_dispositivo as revocar_dispositivo_cu19,
        )

        return revocar_dispositivo_cu19(
            id_dispositivo=int(dispositivo_id),
            db=db,
            user=usuario,
            tenant_id=id_clinica,
        )
    db.commit()


@router.get(
    "/bandeja",
    response_model=List[NotificacionDTO],
    summary="Consultar bandeja de notificaciones y recordatorios del usuario",
)
def consultar_bandeja(
    categoria: Optional[str] = Query(
        default=None,
        description="Filtrar por categoría: TODAS, CITAS, DOCUMENTOS, SISTEMA",
    ),
    solo_no_leidas: bool = Query(default=False),
    limite: int = Query(default=50, ge=1, le=200),
    usuario: Usuario = Depends(get_current_user),
    id_clinica: Optional[int] = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    return NotificacionService(db).listar_bandeja(
        id_usuario=usuario.id_usuario,
        id_clinica=id_clinica,
        categoria=categoria,
        solo_no_leidas=solo_no_leidas,
        limite=limite,
    )


@router.get(
    "/resumen-no-leidas",
    response_model=NotificacionResumenDTO,
    summary="Obtener conteo rápido de notificaciones no leídas para badges de cabecera y sidebar",
)
def obtener_resumen_no_leidas(
    usuario: Usuario = Depends(get_current_user),
    id_clinica: Optional[int] = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    return NotificacionService(db).obtener_resumen_no_leidas(
        id_usuario=usuario.id_usuario,
        id_clinica=id_clinica,
    )


@router.patch(
    "/bandeja/{id_notificacion}/leer",
    response_model=NotificacionDTO,
    summary="Marcar una notificación específica como leída",
)
def marcar_leida(
    id_notificacion: int,
    usuario: Usuario = Depends(get_current_user),
    id_clinica: Optional[int] = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    res = NotificacionService(db).marcar_leida(
        id_usuario=usuario.id_usuario,
        id_notificacion=id_notificacion,
        id_clinica=id_clinica,
    )
    db.commit()
    return res


@router.post(
    "/bandeja/marcar-todas-leidas",
    response_model=MarcarTodasLeidasDTO,
    summary="Marcar todas las notificaciones pendientes del usuario como leídas",
)
def marcar_todas_leidas(
    usuario: Usuario = Depends(get_current_user),
    id_clinica: Optional[int] = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    count = NotificacionService(db).marcar_todas_leidas(
        id_usuario=usuario.id_usuario,
        id_clinica=id_clinica,
    )
    db.commit()
    return MarcarTodasLeidasDTO(actualizadas=count)


@router.get(
    "/preferencias",
    response_model=PreferenciasNotificacionDTO,
    summary="Consultar preferencias de canales de notificación del usuario",
)
def obtener_preferencias(
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return NotificacionService(db).obtener_preferencias(usuario)


@router.put(
    "/preferencias",
    response_model=PreferenciasNotificacionDTO,
    summary="Actualizar preferencias de canales (Push, Email, SMS) del usuario",
)
def actualizar_preferencias(
    dto: PreferenciasNotificacionUpdateDTO,
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = NotificacionService(db).actualizar_preferencias(usuario, dto)
    db.commit()
    return res


@router.post(
    "/emitir",
    response_model=NotificacionDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Emitir una notificación/recordatorio transaccional en el outbox (con control de duplicados)",
)
def emitir_notificacion_endpoint(
    cmd: EmisionNotificacionCommand,
    usuario: Usuario = Depends(get_current_user),
    id_clinica: Optional[int] = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    rol = (usuario.rol or "").upper()
    target_user_id = cmd.id_usuario or usuario.id_usuario
    # Un paciente solo puede emitirse notificaciones de prueba a sí mismo; staff/admin pueden emitir a terceros
    if target_user_id != usuario.id_usuario and rol not in (
        "ADMIN",
        "ADMINISTRADOR",
        "SUPER_ADMIN",
        "SUPERADMIN",
        "MEDICO",
        "DOCTOR",
        "RECEPCION",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para emitir notificaciones a otros usuarios",
        )

    srv = NotificacionService(db)
    notif = srv.emitir_notificacion(
        id_usuario=target_user_id,
        tipo=cmd.tipo,
        titulo=cmd.titulo,
        mensaje=cmd.mensaje,
        id_clinica=id_clinica,
        canal_objetivo=cmd.canal_objetivo,
        canal_badge=cmd.canal_badge,
        recurso_tipo=cmd.recurso_tipo,
        recurso_id=cmd.recurso_id,
        enlace_accion=cmd.enlace_accion,
        fecha_programada=cmd.fecha_programada,
        idempotency_key=cmd.idempotency_key,
        payload_extra=cmd.payload_extra,
    )
    db.commit()
    db.refresh(notif)
    return NotificacionDTO.model_validate(notif)


@router.post(
    "/procesar-outbox",
    response_model=ProcesarOutboxResumenDTO,
    summary="Ejecutar un lote del despachador Outbox de notificaciones",
)
def procesar_outbox_manual(
    limite: int = Query(default=20, ge=1, le=100),
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = NotificacionService(db).procesar_outbox(limite=limite)
    db.commit()
    return ProcesarOutboxResumenDTO(**res)
