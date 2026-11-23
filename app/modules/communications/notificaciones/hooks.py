"""Hooks seguros y desacoplados para emitir notificaciones CU20 desde eventos reales de negocio."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.appointments.models import Cita, Medico
from app.modules.communications.notificaciones.service import NotificacionService
from app.modules.medical_records.models import Paciente

logger = logging.getLogger("notificaciones.hooks")


def _despachar_seguro(db: Session, srv: NotificacionService) -> None:
    try:
        srv.procesar_outbox(limite=5)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 outbox dispatch warning: %s", exc)


def notificar_cita_creada(db: Session, cita: Cita, paciente: Paciente, medico: Medico) -> None:
    """Dispara notificaciones reales al médico y al paciente al agendar una cita."""
    try:
        srv = NotificacionService(db)
        fecha_txt = f"{cita.fecha_cita} {cita.hora_inicio or ''}".strip()
        nom_pac = f"{getattr(paciente, 'nombres', '')} {getattr(paciente, 'apellidos', '')}".strip() or "Un paciente"
        clinica_id = getattr(cita, "id_clinica", None) or getattr(paciente, "id_clinica", None)

        if getattr(medico, "id_usuario", None):
            srv.emitir_notificacion(
                id_usuario=int(medico.id_usuario),
                id_clinica=clinica_id,
                tipo="NUEVA_CITA_AGENDADA",
                titulo="Nueva cita agendada",
                mensaje=f"{nom_pac} reservó una consulta para el {fecha_txt}.",
                canal_objetivo="MULTI",
                canal_badge="Push",
                recurso_tipo="CITA",
                recurso_id=str(cita.id_cita),
                idempotency_key=f"cita-creada-med-{cita.id_cita}",
            )

        if getattr(paciente, "id_usuario", None):
            srv.emitir_notificacion(
                id_usuario=int(paciente.id_usuario),
                id_clinica=clinica_id,
                tipo="RECORDATORIO_CITA",
                titulo="Cita médica confirmada",
                mensaje=f"Tu cita quedó agendada para el {fecha_txt}.",
                canal_objetivo="MULTI",
                canal_badge="Push",
                recurso_tipo="CITA",
                recurso_id=str(cita.id_cita),
                idempotency_key=f"cita-creada-pac-{cita.id_cita}",
            )

        _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001 - nunca romper la operación clínica
        db.rollback()
        logger.warning("CU20 hook crear_cita warning: %s", exc)


def notificar_cita_actualizada(db: Session, cita: Cita, estado_nuevo: Optional[str], cambio_horario: bool) -> None:
    """Notifica cancelaciones o reprogramaciones reales de una cita."""
    try:
        est = (estado_nuevo or "").upper()
        if est != "CANCELADA" and not cambio_horario:
            return

        paciente = db.execute(
            select(Paciente).where(Paciente.id_paciente == cita.id_paciente)
        ).scalars().first()
        medico = db.execute(
            select(Medico).where(Medico.id_medico == cita.id_medico)
        ).scalars().first()

        srv = NotificacionService(db)
        ts_key = int(datetime.now(timezone.utc).timestamp() // 60)
        fecha_txt = f"{cita.fecha_cita} {cita.hora_inicio or ''}".strip()
        clinica_id = getattr(cita, "id_clinica", None)

        if est == "CANCELADA":
            if medico and getattr(medico, "id_usuario", None):
                srv.emitir_notificacion(
                    id_usuario=int(medico.id_usuario),
                    id_clinica=clinica_id,
                    tipo="CITA_CANCELADA",
                    titulo="Cita cancelada",
                    mensaje=f"La cita del {fecha_txt} fue cancelada.",
                    canal_objetivo="PUSH",
                    canal_badge="Push",
                    recurso_tipo="CITA",
                    recurso_id=str(cita.id_cita),
                    idempotency_key=f"cita-cancel-med-{cita.id_cita}-{ts_key}",
                )
            if paciente and getattr(paciente, "id_usuario", None):
                srv.emitir_notificacion(
                    id_usuario=int(paciente.id_usuario),
                    id_clinica=clinica_id,
                    tipo="CITA_CANCELADA",
                    titulo="Tu cita fue cancelada",
                    mensaje=f"Se canceló tu consulta programada para el {fecha_txt}.",
                    canal_objetivo="MULTI",
                    canal_badge="Correo",
                    recurso_tipo="CITA",
                    recurso_id=str(cita.id_cita),
                    idempotency_key=f"cita-cancel-pac-{cita.id_cita}-{ts_key}",
                )
        elif cambio_horario and paciente and getattr(paciente, "id_usuario", None):
            srv.emitir_notificacion(
                id_usuario=int(paciente.id_usuario),
                id_clinica=clinica_id,
                tipo="RECORDATORIO_CITA",
                titulo="Cita reprogramada",
                mensaje=f"Tu consulta fue reprogramada para el {fecha_txt}.",
                canal_objetivo="MULTI",
                canal_badge="Push",
                recurso_tipo="CITA",
                recurso_id=str(cita.id_cita),
                idempotency_key=f"cita-reprog-pac-{cita.id_cita}-{ts_key}",
            )

        _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 hook actualizar_cita warning: %s", exc)


def notificar_presencia_teleconsulta(
    db: Session,
    id_cita: int,
    rol: str,
    conectado: bool,
    nombre: Optional[str] = None,
) -> None:
    """Emite aviso real cuando el médico abre la sala virtual o el paciente entra en espera."""
    if not conectado:
        return
    try:
        cita = db.execute(select(Cita).where(Cita.id_cita == id_cita)).scalars().first()
        if not cita:
            return
        paciente = db.execute(
            select(Paciente).where(Paciente.id_paciente == cita.id_paciente)
        ).scalars().first()
        medico = db.execute(
            select(Medico).where(Medico.id_medico == cita.id_medico)
        ).scalars().first()

        srv = NotificacionService(db)
        rol_up = (rol or "").upper()
        ventana = int(datetime.now(timezone.utc).timestamp() // 300)  # Deduplica en ventanas de 5 min
        clinica_id = getattr(cita, "id_clinica", None)

        if ("DOC" in rol_up or "MED" in rol_up) and paciente and getattr(paciente, "id_usuario", None):
            quien = nombre or "Tu médico"
            srv.emitir_notificacion(
                id_usuario=int(paciente.id_usuario),
                id_clinica=clinica_id,
                tipo="SALA_VIRTUAL_ABIERTA",
                titulo=f"{quien} abrió la sala",
                mensaje="Tu teleconsulta ya está lista. Ingresa a la sala virtual.",
                canal_objetivo="MULTI",
                canal_badge="Push",
                recurso_tipo="SALA_VIRTUAL",
                recurso_id=str(id_cita),
                idempotency_key=f"sala-abierta-{id_cita}-{ventana}",
            )
            _despachar_seguro(db, srv)
        elif "PAC" in rol_up and medico and getattr(medico, "id_usuario", None):
            quien = nombre or "Tu paciente"
            srv.emitir_notificacion(
                id_usuario=int(medico.id_usuario),
                id_clinica=clinica_id,
                tipo="PACIENTE_EN_ESPERA",
                titulo="Paciente en sala de espera",
                mensaje=f"{quien} ya ingresó a la sala virtual de teleconsulta.",
                canal_objetivo="PUSH",
                canal_badge="Push",
                recurso_tipo="SALA_VIRTUAL",
                recurso_id=str(id_cita),
                idempotency_key=f"pac-espera-{id_cita}-{ventana}",
            )
            _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 hook teleconsulta warning: %s", exc)


def notificar_documento_creado(db: Session, doc) -> None:
    """Emite notificación en categoría DOCUMENTOS al paciente cuando se sube un documento/resultado."""
    try:
        if not getattr(doc, "id_paciente", None):
            return
        paciente = db.execute(
            select(Paciente).where(Paciente.id_paciente == doc.id_paciente)
        ).scalars().first()
        if not paciente or not getattr(paciente, "id_usuario", None):
            return

        srv = NotificacionService(db)
        srv.emitir_notificacion(
            id_usuario=int(paciente.id_usuario),
            id_clinica=getattr(doc, "id_clinica", None),
            tipo="DOCUMENTO_DISPONIBLE",
            titulo="Nuevo documento disponible",
            mensaje=f"{getattr(doc, 'titulo', 'Documento clínico')} · {getattr(doc, 'tipo_documento', '')}".strip(" ·"),
            canal_objetivo="EMAIL",
            canal_badge="Correo",
            recurso_tipo="DOCUMENTO",
            recurso_id=str(doc.id_documento),
            idempotency_key=f"doc-creado-{doc.id_documento}",
        )
        _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 hook documento warning: %s", exc)


def notificar_receta_emitida(db: Session, receta) -> None:
    """Emite notificación en categoría DOCUMENTOS al paciente al emitirse una receta digital."""
    try:
        if not getattr(receta, "id_paciente", None):
            return
        paciente = db.execute(
            select(Paciente).where(Paciente.id_paciente == receta.id_paciente)
        ).scalars().first()
        if not paciente or not getattr(paciente, "id_usuario", None):
            return

        srv = NotificacionService(db)
        codigo = getattr(receta, "codigo_verificacion", "") or f"#{receta.id_receta}"
        srv.emitir_notificacion(
            id_usuario=int(paciente.id_usuario),
            id_clinica=getattr(receta, "id_clinica", None),
            tipo="RECETA_EMITIDA",
            titulo="Nueva receta médica digital",
            mensaje=f"Se emitió tu receta digital ({codigo}). Ya puedes consultarla y descargarla.",
            canal_objetivo="MULTI",
            canal_badge="Push",
            recurso_tipo="RECETA",
            recurso_id=str(receta.id_receta),
            idempotency_key=f"receta-emitida-{receta.id_receta}",
        )
        _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 hook receta warning: %s", exc)


def notificar_ficha_creada(db: Session, ficha) -> None:
    """Dispara notificaciones reales al médico y al paciente al agendar una ficha médica (CU09)."""
    try:
        paciente = db.execute(
            select(Paciente).where(Paciente.id_paciente == ficha.id_paciente)
        ).scalars().first()
        medico = db.execute(
            select(Medico).where(Medico.id_medico == ficha.id_medico)
        ).scalars().first()

        srv = NotificacionService(db)
        clinica_id = getattr(ficha, "id_clinica", None)
        fecha_txt = f"{ficha.fecha_atencion} ({ficha.hora_inicio or ''})".strip()
        nom_pac = (
            f"{getattr(paciente, 'nombres', '')} {getattr(paciente, 'apellidos', '')}".strip()
            if paciente
            else "Un paciente"
        )
        correlativo = getattr(ficha, "correlativo", "") or str(ficha.id_ficha)

        if medico and getattr(medico, "id_usuario", None):
            srv.emitir_notificacion(
                id_usuario=int(medico.id_usuario),
                id_clinica=clinica_id,
                tipo="NUEVA_CITA_AGENDADA",
                titulo="Nueva cita / ficha agendada",
                mensaje=f"{nom_pac} reservó la ficha {correlativo} para el {fecha_txt}.",
                canal_objetivo="MULTI",
                canal_badge="Push",
                recurso_tipo="CITA",
                recurso_id=str(ficha.id_ficha),
                enlace_accion=f"/admin/fichas/{ficha.id_ficha}",
                idempotency_key=f"ficha-creada-med-{ficha.id_ficha}",
            )

        if paciente and getattr(paciente, "id_usuario", None):
            srv.emitir_notificacion(
                id_usuario=int(paciente.id_usuario),
                id_clinica=clinica_id,
                tipo="RECORDATORIO_CITA",
                titulo="Ficha médica confirmada",
                mensaje=f"Tu ficha {correlativo} quedó agendada para el {fecha_txt}.",
                canal_objetivo="MULTI",
                canal_badge="Push",
                recurso_tipo="CITA",
                recurso_id=str(ficha.id_ficha),
                enlace_accion=f"/fichas/{ficha.id_ficha}",
                idempotency_key=f"ficha-creada-pac-{ficha.id_ficha}",
            )

        _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 hook crear_ficha warning: %s", exc)


def notificar_ficha_actualizada(db: Session, ficha) -> None:
    """Notifica al paciente en DOCUMENTOS cuando el médico actualiza diagnóstico o finaliza la ficha."""
    try:
        paciente = db.execute(
            select(Paciente).where(Paciente.id_paciente == ficha.id_paciente)
        ).scalars().first()
        if not paciente or not getattr(paciente, "id_usuario", None):
            return

        srv = NotificacionService(db)
        ts_key = int(datetime.now(timezone.utc).timestamp() // 60)
        correlativo = getattr(ficha, "correlativo", "") or str(ficha.id_ficha)
        estado_txt = getattr(ficha, "estado", "ACTUALIZADA")
        srv.emitir_notificacion(
            id_usuario=int(paciente.id_usuario),
            id_clinica=getattr(ficha, "id_clinica", None),
            tipo="DOCUMENTO_DISPONIBLE",
            titulo=f"Ficha {correlativo} actualizada",
            mensaje=f"El médico registró evolución/diagnóstico en tu ficha ({estado_txt}).",
            canal_objetivo="EMAIL",
            canal_badge="Correo",
            recurso_tipo="DOCUMENTO",
            recurso_id=str(ficha.id_ficha),
            enlace_accion=f"/fichas/{ficha.id_ficha}",
            idempotency_key=f"ficha-upd-pac-{ficha.id_ficha}-{ts_key}",
        )
        _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 hook actualizar_ficha warning: %s", exc)


def notificar_ficha_cancelada(db: Session, ficha) -> None:
    """Notifica cancelación de ficha médica a médico y paciente."""
    try:
        paciente = db.execute(
            select(Paciente).where(Paciente.id_paciente == ficha.id_paciente)
        ).scalars().first()
        medico = db.execute(
            select(Medico).where(Medico.id_medico == ficha.id_medico)
        ).scalars().first()

        srv = NotificacionService(db)
        clinica_id = getattr(ficha, "id_clinica", None)
        correlativo = getattr(ficha, "correlativo", "") or str(ficha.id_ficha)

        if medico and getattr(medico, "id_usuario", None):
            srv.emitir_notificacion(
                id_usuario=int(medico.id_usuario),
                id_clinica=clinica_id,
                tipo="CITA_CANCELADA",
                titulo="Ficha médica cancelada",
                mensaje=f"Se canceló la ficha {correlativo} ({ficha.fecha_atencion}).",
                canal_objetivo="PUSH",
                canal_badge="Push",
                recurso_tipo="CITA",
                recurso_id=str(ficha.id_ficha),
                enlace_accion="/admin/fichas",
                idempotency_key=f"ficha-cancel-med-{ficha.id_ficha}",
            )

        if paciente and getattr(paciente, "id_usuario", None):
            srv.emitir_notificacion(
                id_usuario=int(paciente.id_usuario),
                id_clinica=clinica_id,
                tipo="CITA_CANCELADA",
                titulo="Tu ficha fue cancelada",
                mensaje=f"La ficha {correlativo} programada para el {ficha.fecha_atencion} fue cancelada.",
                canal_objetivo="MULTI",
                canal_badge="Correo",
                recurso_tipo="CITA",
                recurso_id=str(ficha.id_ficha),
                enlace_accion="/mis-citas",
                idempotency_key=f"ficha-cancel-pac-{ficha.id_ficha}",
            )

        _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 hook cancelar_ficha warning: %s", exc)


def notificar_orden_laboratorio_firmada(db: Session, orden, doc) -> None:
    """Notifica al paciente en DOCUMENTOS cuando se firma una orden de laboratorio (CU10)."""
    try:
        paciente = db.execute(
            select(Paciente).where(Paciente.id_paciente == orden.id_paciente)
        ).scalars().first()
        if not paciente or not getattr(paciente, "id_usuario", None):
            return

        srv = NotificacionService(db)
        srv.emitir_notificacion(
            id_usuario=int(paciente.id_usuario),
            id_clinica=getattr(orden, "id_clinica", None),
            tipo="DOCUMENTO_DISPONIBLE",
            titulo="Nueva orden de laboratorio",
            mensaje=f"{getattr(doc, 'titulo', 'Orden de exámenes de laboratorio')} ya está disponible.",
            canal_objetivo="EMAIL",
            canal_badge="Correo",
            recurso_tipo="DOCUMENTO",
            recurso_id=str(doc.id_documento),
            enlace_accion=f"/mis-documentos/{doc.id_documento}",
            idempotency_key=f"orden-lab-firmada-{orden.id_orden}",
        )
        _despachar_seguro(db, srv)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("CU20 hook orden_lab warning: %s", exc)
