"""Servicio transaccional CU20: Notificaciones y Recordatorios Multicanal con Outbox."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, func, or_, select, update
from sqlalchemy.orm import Session

from app.modules.auth.models import Usuario
from app.modules.communications.notificaciones.adapters import (
    EmailAdapter,
    FCMPushAdapter,
    SmsAdapter,
    WebPushAdapter,
)
from app.modules.communications.notificaciones.crypto_webpush import obtener_vapid_public_key
from app.modules.communications.notificaciones.models import (
    DispositivoAutorizado,
    EventoOutbox,
    Notificacion,
)
from app.modules.communications.notificaciones.schemas import (
    DispositivoDTO,
    NotificacionDTO,
    NotificacionResumenDTO,
    PreferenciasNotificacionDTO,
    PreferenciasNotificacionUpdateDTO,
    RegistroDispositivoDTO,
)

logger = logging.getLogger("notificaciones.service")

TIPOS_CITAS = {
    "SALA_VIRTUAL_ABIERTA",
    "TURNO_LIBERADO",
    "RECORDATORIO_CITA",
    "NUEVA_CITA_AGENDADA",
    "PACIENTE_EN_ESPERA",
    "CITA_CANCELADA",
    "PAGO_CONFIRMADO",
}

TIPOS_DOCUMENTOS = {
    "DOCUMENTO_DISPONIBLE",
    "RESULTADO_LAB_LISTO",
    "RECETA_EMITIDA",
    "MEDICACION_TRATAMIENTO",
}


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalizar_rol(usuario: Optional[Usuario]) -> str:
    if usuario is None:
        return "PACIENTE"
    rol = getattr(usuario, "rol", None)
    if isinstance(rol, str) and rol.strip():
        return rol.strip().upper()
    rel = getattr(usuario, "rol_rel", None)
    if rel is not None and getattr(rel, "nombre", None):
        return str(rel.nombre).strip().upper()
    return "PACIENTE"


def resolver_categoria(tipo: str, recurso_tipo: Optional[str] = None) -> str:
    t = (tipo or "").upper()
    r = (recurso_tipo or "").upper()
    if t in TIPOS_CITAS or r in ("CITA", "SALA_VIRTUAL", "TELECONSULTA", "PAGO"):
        return "CITAS"
    if t in TIPOS_DOCUMENTOS or r in ("DOCUMENTO", "RECETA", "TRATAMIENTO", "LABORATORIO"):
        return "DOCUMENTOS"
    return "SISTEMA"


def resolver_enlace_accion(
    rol: str,
    tipo: str,
    recurso_tipo: Optional[str],
    recurso_id: Optional[str],
) -> str:
    rol_u = (rol or "PACIENTE").upper()
    t = (tipo or "").upper()
    r = (recurso_tipo or "").upper()

    if rol_u in ("MEDICO", "DOCTOR"):
        if t == "PACIENTE_EN_ESPERA" or r in ("SALA_VIRTUAL", "TELECONSULTA"):
            return f"/admin/teleconsulta/{recurso_id}" if recurso_id else "/admin/teleconsulta"
        if t == "CITA_CANCELADA":
            return "/admin/agenda"
        if t == "NUEVA_CITA_AGENDADA" or r == "CITA":
            return "/admin/consultas"
        if t == "RESULTADO_LAB_LISTO" or r in ("DOCUMENTO", "LABORATORIO"):
            return f"/admin/documentos/{recurso_id}" if recurso_id else "/admin/documentos"
        return "/admin/inicio-medico"

    if rol_u in ("ADMIN", "ADMINISTRADOR", "SUPER_ADMIN", "SUPERADMIN"):
        if t == "BACKUP" or r == "BACKUP":
            return "/admin/backups"
        return "/admin/dashboard"

    # PACIENTE (default)
    if t == "SALA_VIRTUAL_ABIERTA" or r in ("SALA_VIRTUAL", "TELECONSULTA"):
        return f"/citas/{recurso_id}/teleconsulta" if recurso_id else "/teleconsulta"
    if t in ("TURNO_LIBERADO", "RECORDATORIO_CITA", "PAGO_CONFIRMADO") or r in ("CITA", "PAGO"):
        return "/mis-citas"
    if t == "MEDICACION_TRATAMIENTO" or r in ("TRATAMIENTO", "RECETA"):
        return "/recetas"
    if t == "DOCUMENTO_DISPONIBLE" or r in ("DOCUMENTO", "LABORATORIO"):
        return f"/mis-documentos/{recurso_id}" if recurso_id else "/mis-documentos"
    return "/notificaciones"


def resolver_canal_badge(
    canal_objetivo: str,
    canal_badge: Optional[str] = None,
    payload_extra: Optional[Dict[str, Any]] = None,
) -> str:
    if canal_badge and canal_badge.strip():
        return canal_badge.strip()
    proveedor = str((payload_extra or {}).get("proveedor", "")).lower().strip()
    if proveedor == "whatsapp":
        return "WhatsApp"
    c = (canal_objetivo or "PUSH").upper()
    if c == "EMAIL":
        return "Correo"
    if c == "SMS":
        return "SMS"
    return "Push"


class NotificacionService:
    """Servicio central CU20 con Outbox transaccional, deduplicación y despacho multicanal."""

    @staticmethod
    def obtener_clave_publica_vapid() -> str:
        return obtener_vapid_public_key()

    def __init__(
        self,
        db: Session,
        adapter_webpush: Optional[WebPushAdapter] = None,
        adapter_fcm: Optional[FCMPushAdapter] = None,
        adapter_email: Optional[EmailAdapter] = None,
        adapter_sms: Optional[SmsAdapter] = None,
    ):
        self.db = db
        self.adapter_webpush = adapter_webpush or WebPushAdapter()
        self.adapter_fcm = adapter_fcm or FCMPushAdapter()
        self.adapter_email = adapter_email or EmailAdapter()
        self.adapter_sms = adapter_sms or SmsAdapter()

    # ------------------------------------------------------------------ #
    # Registro y revocación de dispositivos Push
    # ------------------------------------------------------------------ #

    def registrar_dispositivo(
        self,
        usuario: Usuario,
        dto: RegistroDispositivoDTO,
        id_clinica: Optional[int] = None,
    ) -> DispositivoDTO:
        clinica_id = id_clinica if id_clinica is not None else usuario.id_clinica
        token_bytes = dto.push_token.encode("utf-8") if dto.push_token else None
        token_hash = hashlib.sha256(token_bytes).hexdigest() if token_bytes else None

        stmt = select(DispositivoAutorizado).where(
            DispositivoAutorizado.id_usuario == usuario.id_usuario,
            DispositivoAutorizado.canal == dto.canal,
            DispositivoAutorizado.dispositivo_id == dto.dispositivo_id,
        )
        disp = self.db.execute(stmt).scalars().first()
        ahora = _ahora_utc()

        if disp:
            disp.id_clinica = clinica_id
            disp.rol_usuario = _normalizar_rol(usuario)
            disp.estado = "ACTIVO"
            disp.push_destino_cifrado = token_bytes
            disp.push_destino_hash = token_hash
            disp.revision += 1
            disp.revocado_en = None
        else:
            disp = DispositivoAutorizado(
                id_clinica=clinica_id,
                id_usuario=usuario.id_usuario,
                rol_usuario=_normalizar_rol(usuario),
                canal=dto.canal,
                dispositivo_id=dto.dispositivo_id,
                push_destino_cifrado=token_bytes,
                push_destino_hash=token_hash,
                estado="ACTIVO",
                revision=1,
                creado_en=ahora,
            )
            self.db.add(disp)

        self.db.flush()
        return DispositivoDTO.model_validate(disp)

    def revocar_dispositivo(self, id_usuario: int, dispositivo_id: str) -> int:
        stmt = select(DispositivoAutorizado).where(
            DispositivoAutorizado.id_usuario == id_usuario,
            DispositivoAutorizado.dispositivo_id == dispositivo_id,
            DispositivoAutorizado.estado == "ACTIVO",
        )
        dispositivos = list(self.db.execute(stmt).scalars().all())
        ahora = _ahora_utc()
        for disp in dispositivos:
            disp.estado = "REVOCADO"
            disp.revocado_en = ahora
            disp.revision += 1
        self.db.flush()
        return len(dispositivos)

    def listar_dispositivos(self, id_usuario: int) -> List[DispositivoDTO]:
        stmt = (
            select(DispositivoAutorizado)
            .where(
                DispositivoAutorizado.id_usuario == id_usuario,
                DispositivoAutorizado.estado == "ACTIVO",
            )
            .order_by(desc(DispositivoAutorizado.creado_en))
        )
        rows = self.db.execute(stmt).scalars().all()
        return [DispositivoDTO.model_validate(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Emisión Transaccional + Control de Duplicados (Idempotencia)
    # ------------------------------------------------------------------ #

    def emitir_notificacion(
        self,
        id_usuario: int,
        tipo: str,
        titulo: str,
        mensaje: str,
        id_clinica: Optional[int] = None,
        canal_objetivo: str = "MULTI",
        canal_badge: Optional[str] = None,
        recurso_tipo: Optional[str] = None,
        recurso_id: Optional[str] = None,
        enlace_accion: Optional[str] = None,
        fecha_programada: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
        payload_extra: Optional[Dict[str, Any]] = None,
        dispositivo_id: Optional[str] = None,
    ) -> Notificacion:
        """Inserta atómicamente el evento Outbox y la notificación en bandeja con deduplicación."""
        usuario = self.db.execute(
            select(Usuario).where(Usuario.id_usuario == id_usuario)
        ).scalars().first()
        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario destinatario no encontrado",
            )

        clinica_id = id_clinica if id_clinica is not None else usuario.id_clinica
        rol_dest = _normalizar_rol(usuario)
        categoria = resolver_categoria(tipo, recurso_tipo)
        enlace = enlace_accion or resolver_enlace_accion(rol_dest, tipo, recurso_tipo, recurso_id)
        badge = resolver_canal_badge(canal_objetivo, canal_badge, payload_extra)

        ahora = _ahora_utc()
        prog_str = fecha_programada.isoformat() if fecha_programada else ""
        base_idem = (
            idempotency_key
            if idempotency_key
            else f"{clinica_id}|{id_usuario}|{tipo}|{recurso_tipo or ''}|{recurso_id or ''}|{prog_str}|{titulo}"
        )
        idempotency_hash = hashlib.sha256(base_idem.encode("utf-8")).hexdigest()

        # Control estricto de duplicados
        existente_outbox = self.db.execute(
            select(EventoOutbox).where(EventoOutbox.idempotency_hash == idempotency_hash)
        ).scalars().first()
        if existente_outbox:
            existente_notif = self.db.execute(
                select(Notificacion).where(Notificacion.outbox_id == existente_outbox.id_evento)
            ).scalars().first()
            if existente_notif:
                return existente_notif

        payload_completo: Dict[str, Any] = {
            "titulo": titulo,
            "cuerpo": mensaje,
            "tipo": tipo,
            "categoria": categoria,
            "rol_destinatario": rol_dest,
            "recurso_tipo": recurso_tipo or "NOTIFICACION",
            "recurso_id": str(recurso_id) if recurso_id is not None else "",
            "url": enlace,
            "canal_badge": badge,
            **(payload_extra or {}),
        }

        outbox = EventoOutbox(
            id_clinica=clinica_id,
            id_usuario_destino=id_usuario,
            recurso_tipo=recurso_tipo or "NOTIFICACION",
            recurso_id=str(recurso_id) if recurso_id is not None else "0",
            transicion=tipo,
            canal_objetivo=canal_objetivo.upper(),
            revision=1,
            dispositivo_id=dispositivo_id,
            idempotency_hash=idempotency_hash,
            payload=payload_completo,
            estado="PENDIENTE",
            intentos=0,
            max_intentos=3,
            proximo_intento_en=fecha_programada,
            creado_en=ahora,
        )
        self.db.add(outbox)
        self.db.flush()

        notif = Notificacion(
            id_clinica=clinica_id,
            id_usuario=id_usuario,
            outbox_id=outbox.id_evento,
            rol_destinatario=rol_dest,
            tipo=tipo,
            categoria=categoria,
            canal=canal_objetivo.upper(),
            canal_badge=badge,
            titulo=titulo,
            mensaje=mensaje,
            recurso_tipo=recurso_tipo,
            recurso_id=str(recurso_id) if recurso_id is not None else None,
            enlace_accion=enlace,
            payload_extra=payload_extra,
            fecha_programada=fecha_programada or ahora,
            estado="PENDIENTE",
            created_at=ahora,
        )
        self.db.add(notif)
        self.db.flush()
        return notif

    # ------------------------------------------------------------------ #
    # Consulta de Bandeja, Resumen y Lectura (Segregada por Usuario/Tenant)
    # ------------------------------------------------------------------ #

    def _filtro_base_bandeja(self, id_usuario: int, id_clinica: Optional[int]):
        conds = [Notificacion.id_usuario == id_usuario]
        if id_clinica is not None:
            conds.append(
                or_(Notificacion.id_clinica == id_clinica, Notificacion.id_clinica.is_(None))
            )
        return conds

    def listar_bandeja(
        self,
        id_usuario: int,
        id_clinica: Optional[int] = None,
        categoria: Optional[str] = None,
        solo_no_leidas: bool = False,
        limite: int = 50,
    ) -> List[NotificacionDTO]:
        conds = self._filtro_base_bandeja(id_usuario, id_clinica)
        if categoria and categoria.upper() not in ("TODAS", "ALL"):
            conds.append(Notificacion.categoria == categoria.upper())
        if solo_no_leidas:
            conds.append(Notificacion.fecha_lectura.is_(None))

        stmt = (
            select(Notificacion)
            .where(*conds)
            .order_by(desc(Notificacion.created_at), desc(Notificacion.id_notificacion))
            .limit(min(max(limite, 1), 200))
        )
        filas = self.db.execute(stmt).scalars().all()
        return [NotificacionDTO.model_validate(f) for f in filas]

    def obtener_resumen_no_leidas(
        self,
        id_usuario: int,
        id_clinica: Optional[int] = None,
    ) -> NotificacionResumenDTO:
        conds = self._filtro_base_bandeja(id_usuario, id_clinica)
        total = self.db.execute(
            select(func.count(Notificacion.id_notificacion)).where(*conds)
        ).scalar_one()

        no_leidas_conds = [*conds, Notificacion.fecha_lectura.is_(None)]
        no_leidas = self.db.execute(
            select(func.count(Notificacion.id_notificacion)).where(*no_leidas_conds)
        ).scalar_one()

        rows_cat = self.db.execute(
            select(Notificacion.categoria, func.count(Notificacion.id_notificacion))
            .where(*no_leidas_conds)
            .group_by(Notificacion.categoria)
        ).all()
        por_categoria = {str(cat or "SISTEMA"): int(cnt) for cat, cnt in rows_cat}

        return NotificacionResumenDTO(
            no_leidas=int(no_leidas),
            total=int(total),
            por_categoria=por_categoria,
        )

    def marcar_leida(
        self,
        id_usuario: int,
        id_notificacion: int,
        id_clinica: Optional[int] = None,
    ) -> NotificacionDTO:
        conds = [
            Notificacion.id_notificacion == id_notificacion,
            *self._filtro_base_bandeja(id_usuario, id_clinica),
        ]
        notif = self.db.execute(select(Notificacion).where(*conds)).scalars().first()
        if not notif:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notificación no encontrada",
            )
        if notif.fecha_lectura is None:
            notif.fecha_lectura = _ahora_utc()
            notif.estado = "LEIDA"
            self.db.flush()
        return NotificacionDTO.model_validate(notif)

    def marcar_todas_leidas(
        self,
        id_usuario: int,
        id_clinica: Optional[int] = None,
    ) -> int:
        conds = [
            *self._filtro_base_bandeja(id_usuario, id_clinica),
            Notificacion.fecha_lectura.is_(None),
        ]
        ahora = _ahora_utc()
        result = self.db.execute(
            update(Notificacion)
            .where(*conds)
            .values(fecha_lectura=ahora, estado="LEIDA")
        )
        self.db.flush()
        return int(result.rowcount or 0)

    # ------------------------------------------------------------------ #
    # Preferencias de canales del usuario
    # ------------------------------------------------------------------ #

    def obtener_preferencias(self, usuario: Usuario) -> PreferenciasNotificacionDTO:
        return PreferenciasNotificacionDTO(
            notificaciones_push=bool(usuario.notificaciones_push),
            notificaciones_email=bool(usuario.notificaciones_email),
            notificaciones_sms=bool(usuario.notificaciones_sms),
        )

    def actualizar_preferencias(
        self,
        usuario: Usuario,
        dto: PreferenciasNotificacionUpdateDTO,
    ) -> PreferenciasNotificacionDTO:
        if dto.notificaciones_push is not None:
            usuario.notificaciones_push = dto.notificaciones_push
        if dto.notificaciones_email is not None:
            usuario.notificaciones_email = dto.notificaciones_email
        if dto.notificaciones_sms is not None:
            usuario.notificaciones_sms = dto.notificaciones_sms
        self.db.flush()
        return self.obtener_preferencias(usuario)

    # ------------------------------------------------------------------ #
    # Worker Outbox Multicanal (FOR UPDATE SKIP LOCKED + Backoff)
    # ------------------------------------------------------------------ #

    def procesar_outbox(self, limite: int = 20) -> Dict[str, int]:
        ahora = _ahora_utc()
        stmt = (
            select(EventoOutbox)
            .where(
                EventoOutbox.estado.in_(["PENDIENTE", "REINTENTO"]),
                or_(
                    EventoOutbox.proximo_intento_en.is_(None),
                    EventoOutbox.proximo_intento_en <= ahora,
                ),
            )
            .order_by(EventoOutbox.creado_en.asc())
            .limit(limite)
        )

        # PostgreSQL soporta FOR UPDATE SKIP LOCKED; SQLite no lo requiere en tests
        dialect = self.db.bind.dialect.name if self.db.bind is not None else ""
        if dialect == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        eventos = list(self.db.execute(stmt).scalars().all())
        resumen = {
            "procesados": 0,
            "enviados": 0,
            "reintentos": 0,
            "fallidos": 0,
            "sin_destinos": 0,
        }

        for ev in eventos:
            resumen["procesados"] += 1
            ev.intentos += 1
            if ev.intentos > ev.max_intentos:
                ev.estado = "FALLIDO"
                resumen["fallidos"] += 1
                self._actualizar_estado_notificacion(ev.id_evento, "FALLIDO", None)
                continue

            usuario = self.db.execute(
                select(Usuario).where(Usuario.id_usuario == ev.id_usuario_destino)
            ).scalars().first()
            if not usuario:
                ev.estado = "SIN_DESTINOS"
                resumen["sin_destinos"] += 1
                continue

            payload_dict = dict(ev.payload or {})
            destinos_res: Dict[str, str] = dict(payload_dict.get("_destinos_resultado") or {})
            titulo = str(payload_dict.get("titulo", "Nueva notificación"))
            cuerpo = str(payload_dict.get("cuerpo", ""))
            enlace = payload_dict.get("url")

            canal_obj = (ev.canal_objetivo or "MULTI").upper()
            usar_push = canal_obj == "PUSH" or (canal_obj == "MULTI" and bool(usuario.notificaciones_push))
            usar_email = canal_obj == "EMAIL" or (canal_obj == "MULTI" and bool(usuario.notificaciones_email))
            usar_sms = canal_obj == "SMS" or (canal_obj == "MULTI" and bool(usuario.notificaciones_sms))

            total_destinos = 0
            exitosos = 0
            reintentables = 0
            errores: List[str] = []

            # 1. Canal Push (PWA + FLUTTER)
            if usar_push:
                q_disp = select(DispositivoAutorizado).where(
                    DispositivoAutorizado.id_usuario == usuario.id_usuario,
                    DispositivoAutorizado.estado == "ACTIVO",
                )
                if ev.dispositivo_id:
                    q_disp = q_disp.where(DispositivoAutorizado.dispositivo_id == ev.dispositivo_id)
                disps = [d for d in self.db.execute(q_disp).scalars().all() if d.push_destino_cifrado]

                for disp in disps:
                    total_destinos += 1
                    key = f"push:{disp.id_dispositivo}"
                    if destinos_res.get(key) == "ACEPTADO":
                        exitosos += 1
                        continue

                    token_str = disp.push_destino_cifrado.decode("utf-8", errors="ignore")
                    adapter = self.adapter_webpush if disp.canal == "PWA" else self.adapter_fcm
                    res = adapter.enviar(token_str, titulo, cuerpo, payload_dict)
                    destinos_res[key] = res.codigo

                    if res.token_invalido:
                        disp.estado = "REVOCADO"
                        disp.revocado_en = ahora
                        disp.revision += 1

                    if res.exito:
                        exitosos += 1
                    else:
                        if res.reintentable:
                            reintentables += 1
                        errores.append(f"{key}:{res.codigo}({res.detalle or ''})")

            # 2. Canal Email
            if usar_email and usuario.correo:
                total_destinos += 1
                key = "email"
                if destinos_res.get(key) == "ACEPTADO":
                    exitosos += 1
                else:
                    res = self.adapter_email.enviar(usuario.correo, titulo, cuerpo, enlace=enlace)
                    destinos_res[key] = res.codigo
                    if res.exito:
                        exitosos += 1
                    else:
                        if res.reintentable:
                            reintentables += 1
                        errores.append(f"email:{res.codigo}({res.detalle or ''})")

            # 3. Canal SMS
            if usar_sms and usuario.telefono:
                total_destinos += 1
                key = "sms"
                if destinos_res.get(key) == "ACEPTADO":
                    exitosos += 1
                else:
                    res = self.adapter_sms.enviar(usuario.telefono, titulo, cuerpo)
                    destinos_res[key] = res.codigo
                    if res.exito:
                        exitosos += 1
                    else:
                        if res.reintentable:
                            reintentables += 1
                        errores.append(f"sms:{res.codigo}({res.detalle or ''})")

            payload_dict["_destinos_resultado"] = destinos_res
            ev.payload = payload_dict
            ev.ultimo_error = "; ".join(errores)[:500] if errores else None

            if total_destinos == 0:
                ev.estado = "SIN_DESTINOS"
                resumen["sin_destinos"] += 1
                self._actualizar_estado_notificacion(ev.id_evento, "ENVIADO", ahora)
            elif exitosos == total_destinos:
                ev.estado = "ENVIADO"
                ev.entregado_en = ahora
                resumen["enviados"] += 1
                self._actualizar_estado_notificacion(ev.id_evento, "ENVIADO", ahora)
            elif reintentables > 0 and ev.intentos < ev.max_intentos:
                ev.estado = "REINTENTO"
                backoff_seg = 60 * (2 ** (ev.intentos - 1))
                ev.proximo_intento_en = ahora + timedelta(seconds=backoff_seg)
                resumen["reintentos"] += 1
            else:
                ev.estado = "FALLIDO_PARCIAL" if exitosos > 0 else "FALLIDO"
                resumen["fallidos"] += 1
                self._actualizar_estado_notificacion(
                    ev.id_evento,
                    "ENVIADO" if exitosos > 0 else "FALLIDO",
                    ahora if exitosos > 0 else None,
                )

        self.db.flush()
        return resumen

    def _actualizar_estado_notificacion(
        self,
        outbox_id: int,
        nuevo_estado: str,
        fecha_envio: Optional[datetime],
    ) -> None:
        notif = self.db.execute(
            select(Notificacion).where(Notificacion.outbox_id == outbox_id)
        ).scalars().first()
        if not notif:
            return
        if notif.fecha_lectura is None:
            notif.estado = nuevo_estado
        if fecha_envio is not None and notif.fecha_envio is None:
            notif.fecha_envio = fecha_envio
