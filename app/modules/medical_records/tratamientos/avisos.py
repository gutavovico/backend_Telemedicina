"""Generación y despacho de recordatorios CU17; ejecutable por un worker externo."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from sqlalchemy import exists, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload

from app.core.config import settings
from app.modules.appointments.models import Medico
from app.core.audit import registrar_auditoria
from app.modules.auth.models import Rol, Usuario
from app.modules.medical_records.models import Paciente
from app.modules.medical_records.prescriptions.models import Receta
from app.modules.medical_records.tratamientos.avisos_models import (
    TratamientoAviso, TratamientoCursor, TratamientoDispositivo, TratamientoEntregaPush,
)
from app.modules.medical_records.tratamientos.models import (
    Tratamiento, TratamientoDosis, TratamientoEvento, TratamientoMedicamento,
)

MAX_INTENTOS = 5


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fernet() -> Fernet:
    key = settings.CU17_DEVICE_TOKEN_KEY.get_secret_value()
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise RuntimeError("Configuración de cifrado CU17 no disponible") from None


def push_configurado() -> bool:
    """La configuración no implica que el proveedor haya confirmado un envío."""
    project = settings.CU17_FCM_PROJECT_ID.strip()
    credential_path = settings.CU17_FCM_SERVICE_ACCOUNT_FILE.strip()
    if not project or not credential_path or not Path(credential_path).is_file():
        return False
    try:
        _fernet()
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleRequest  # noqa: F401
        service_account.Credentials.from_service_account_file(
            credential_path, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    except Exception:
        return False
    return True


def cifrar_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def enviar_fcm(token: str, titulo: str, mensaje: str, id_tratamiento: int, id_aviso: int) -> None:
    """Entrega mediante FCM HTTP v1. Lanza excepción si FCM no confirma el envío."""
    if not push_configurado():
        raise RuntimeError("PROVEEDOR_NO_CONFIGURADO")
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        settings.CU17_FCM_SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/firebase.messaging"],
    )
    credentials.refresh(GoogleRequest())
    project = settings.CU17_FCM_PROJECT_ID.strip()
    payload = {"message": {"token": token, "notification": {"title": titulo, "body": mensaje},
                           "data": {"id_tratamiento": str(id_tratamiento), "id_aviso": str(id_aviso)}}}
    request = Request(
        f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or not result.get("name"):
            raise RuntimeError("FCM_SIN_CONFIRMACION")


def _receta_valida(db: Session, plan: Tratamiento) -> bool:
    if plan.id_receta is None:
        return True
    estado = db.execute(select(Receta.estado).where(
        Receta.id_receta == plan.id_receta, Receta.id_clinica == plan.id_clinica,
    )).scalar_one_or_none()
    return estado == "EMITIDA"


def _usuario_paciente(db: Session, plan: Tratamiento):
    return db.execute(select(Usuario).options(lazyload(Usuario.rol_rel)).join(Paciente, Paciente.id_usuario == Usuario.id_usuario).where(
        Paciente.id_paciente == plan.id_paciente, Paciente.id_clinica == plan.id_clinica,
        Usuario.id_clinica == plan.id_clinica,
    )).scalar_one_or_none()


def _usuario_medico(db: Session, plan: Tratamiento):
    return db.execute(select(Usuario).options(lazyload(Usuario.rol_rel)).join(Medico, Medico.id_usuario == Usuario.id_usuario).where(
        Medico.id_medico == plan.id_medico, Usuario.id_clinica == plan.id_clinica,
    )).scalar_one_or_none()


def _crear_aviso(db: Session, plan: Tratamiento, dosis: TratamientoDosis, user: Usuario,
                  tipo: str, canal: str, now: datetime):
    condiciones = (TratamientoAviso.id_clinica == plan.id_clinica,
                   TratamientoAviso.id_dosis == dosis.id_dosis,
                   TratamientoAviso.id_usuario == user.id_usuario,
                   TratamientoAviso.tipo == tipo, TratamientoAviso.canal == canal)
    actual = db.execute(select(TratamientoAviso).where(*condiciones)).scalar_one_or_none()
    if actual is not None:
        return actual, False
    titulos = {"RECORDATORIO": "Recordatorio de tratamiento", "OMISION": "Toma pendiente",
               "RIESGO_ABANDONO": "Seguimiento de tratamiento"}
    mensajes = {"RECORDATORIO": "Tienes una toma programada próximamente.",
                "OMISION": "Tienes una toma pendiente de registrar.",
                "RIESGO_ABANDONO": "Revisa el seguimiento del tratamiento en la aplicación."}
    aviso = TratamientoAviso(id_clinica=plan.id_clinica, id_tratamiento=plan.id_tratamiento,
                             id_dosis=dosis.id_dosis, id_usuario=user.id_usuario, tipo=tipo,
                             canal=canal, titulo=titulos[tipo], mensaje=mensajes[tipo],
                             programada_en_utc=now, estado="PENDIENTE", intentos=0)
    try:
        with db.begin_nested():
            db.add(aviso)
            db.flush()
    except IntegrityError:
        return db.execute(select(TratamientoAviso).where(*condiciones)).scalar_one(), False
    return aviso, True


def _avisar(db: Session, plan: Tratamiento, dosis: TratamientoDosis, user: Usuario,
           tipo: str, now: datetime, push: bool) -> int:
    _, nuevo = _crear_aviso(db, plan, dosis, user, tipo, "WEB", now)
    count = int(nuevo)
    if not push or not user.notificaciones_push:
        return count
    dispositivos = db.execute(select(TratamientoDispositivo).where(
        TratamientoDispositivo.id_clinica == plan.id_clinica,
        TratamientoDispositivo.id_usuario == user.id_usuario,
        TratamientoDispositivo.activo.is_(True),
    )).scalars().all()
    if not dispositivos:
        return count
    aviso, creado = _crear_aviso(db, plan, dosis, user, tipo, "PUSH", now)
    count += int(creado)
    # Solo se incorporan dispositivos vigentes al crear el aviso. La unicidad
    # protege la operación frente a la repetición de un ciclo.
    if creado:
        for dispositivo in dispositivos:
            db.add(TratamientoEntregaPush(id_clinica=plan.id_clinica, id_aviso=aviso.id_aviso,
                                         id_dispositivo=dispositivo.id_dispositivo,
                                         estado="PENDIENTE", intentos=0))
    return count


def _puntual(dosis: TratamientoDosis) -> bool:
    if dosis.estado != "INGERIDA" or dosis.efectiva_en_utc is None:
        return False
    programada = _utc(dosis.programada_en_utc)
    return programada - timedelta(minutes=30) <= _utc(dosis.efectiva_en_utc) <= programada + timedelta(minutes=60)


def generar_avisos(db: Session, *, now: datetime | None = None, fechas_cubiertas=None) -> int:
    """Produce avisos únicos y conserva las tomas aun si no hay proveedor push."""
    now = _utc(now or _now())
    base = (
        select(TratamientoDosis, TratamientoMedicamento, Tratamiento)
        .join(TratamientoMedicamento, TratamientoMedicamento.id_medicamento_plan == TratamientoDosis.id_medicamento_plan)
        .join(Tratamiento, Tratamiento.id_tratamiento == TratamientoMedicamento.id_tratamiento)
        .where(TratamientoDosis.id_clinica == TratamientoMedicamento.id_clinica,
               TratamientoMedicamento.id_clinica == Tratamiento.id_clinica,
               Tratamiento.estado == "ACTIVO", TratamientoMedicamento.estado == "ACTIVO",
               TratamientoDosis.cancelada_en_utc.is_(None),
               or_(Tratamiento.id_receta.is_(None), exists(select(Receta.id_receta).where(
                   Receta.id_receta == Tratamiento.id_receta,
                   Receta.id_clinica == Tratamiento.id_clinica, Receta.estado == "EMITIDA"))),
               exists(select(Paciente.id_paciente).join(Usuario, Usuario.id_usuario == Paciente.id_usuario).where(
                   Paciente.id_paciente == Tratamiento.id_paciente,
                   Paciente.id_clinica == Tratamiento.id_clinica,
                   Usuario.id_clinica == Tratamiento.id_clinica, Usuario.estado.ilike("activo"))))
    )
    recordatorios = db.execute(base.where(
        TratamientoDosis.programada_en_utc >= now,
        TratamientoDosis.programada_en_utc <= now + timedelta(minutes=30),
        TratamientoDosis.estado != "INGERIDA",
        ~exists(select(TratamientoAviso.id_aviso).where(
            TratamientoAviso.id_clinica == TratamientoDosis.id_clinica,
            TratamientoAviso.id_dosis == TratamientoDosis.id_dosis,
            TratamientoAviso.tipo == "RECORDATORIO", TratamientoAviso.canal == "WEB")),
    ).order_by(TratamientoDosis.programada_en_utc, TratamientoDosis.id_dosis).limit(1000)).all()
    consulta_vencidas = base.where(
        TratamientoDosis.programada_en_utc < now - timedelta(minutes=60),
        TratamientoDosis.alertas_evaluadas_en_utc.is_(None),
    )
    vencidas = []
    if fechas_cubiertas is None:
        vencidas = db.execute(consulta_vencidas.order_by(
            TratamientoDosis.programada_en_utc, TratamientoDosis.id_dosis).limit(1000)).all()
    else:
        # Un tratamiento con años pendientes no desplaza los avisos de otro.
        for (clinica, plan_id), (hasta, zona) in fechas_cubiertas.items():
            limite = datetime.combine(hasta, time.min, tzinfo=ZoneInfo(zona)).astimezone(timezone.utc)
            vencidas.extend(db.execute(consulta_vencidas.where(
                Tratamiento.id_clinica == clinica, Tratamiento.id_tratamiento == plan_id,
                TratamientoDosis.programada_en_utc < limite,
            ).order_by(TratamientoDosis.programada_en_utc, TratamientoDosis.id_dosis).limit(100)).all())
    creados = 0
    for dosis, medicamento, plan in recordatorios:
        if not _receta_valida(db, plan):
            continue
        paciente = _usuario_paciente(db, plan)
        if paciente is None or (paciente.estado or "").upper() != "ACTIVO":
            continue
        creados += _avisar(db, plan, dosis, paciente, "RECORDATORIO", now, True)
    for dosis, medicamento, plan in vencidas:
        if not _receta_valida(db, plan):
            continue
        paciente = _usuario_paciente(db, plan)
        if paciente is None or (paciente.estado or "").upper() != "ACTIVO":
            continue
        if dosis.estado != "INGERIDA":
            creados += _avisar(db, plan, dosis, paciente, "OMISION", now, True)
        recientes = db.execute(select(TratamientoDosis).where(
            TratamientoDosis.id_clinica == plan.id_clinica,
            TratamientoDosis.id_medicamento_plan == medicamento.id_medicamento_plan,
            TratamientoDosis.cancelada_en_utc.is_(None),
            TratamientoDosis.programada_en_utc <= dosis.programada_en_utc,
        ).order_by(TratamientoDosis.programada_en_utc.desc(), TratamientoDosis.id_dosis.desc()).limit(4)).scalars().all()
        if len(recientes) >= 3 and all(not _puntual(item) for item in recientes[:3]) and (
            len(recientes) == 3 or _puntual(recientes[3])
        ):
            creados += _avisar(db, plan, dosis, paciente, "RIESGO_ABANDONO", now, True)
            medico = _usuario_medico(db, plan)
            if medico is not None and (medico.estado or "").upper() == "ACTIVO":
                creados += _avisar(db, plan, dosis, medico, "RIESGO_ABANDONO", now, False)
        dosis.alertas_evaluadas_en_utc = now
    db.flush()
    return creados


def despachar_push(db: Session, *, now: datetime | None = None, sender=enviar_fcm) -> int:
    """Reintenta por dispositivo con backoff, sin reenviar entregas ya confirmadas."""
    now = _utc(now or _now())
    entregas = db.execute(select(TratamientoEntregaPush).where(
        TratamientoEntregaPush.estado.in_(["PENDIENTE", "FALLIDO"]),
        TratamientoEntregaPush.intentos < MAX_INTENTOS,
        (TratamientoEntregaPush.proximo_intento_en_utc.is_(None) |
         (TratamientoEntregaPush.proximo_intento_en_utc <= now)),
    ).with_for_update(skip_locked=True)).scalars().all()
    enviados = 0
    for entrega in entregas:
        aviso = db.execute(select(TratamientoAviso).where(
            TratamientoAviso.id_aviso == entrega.id_aviso,
            TratamientoAviso.id_clinica == entrega.id_clinica)).scalar_one_or_none()
        dispositivo = db.execute(select(TratamientoDispositivo).where(
            TratamientoDispositivo.id_dispositivo == entrega.id_dispositivo,
            TratamientoDispositivo.id_clinica == entrega.id_clinica)).scalar_one_or_none()
        if aviso is None or dispositivo is None:
            continue
        plan = db.execute(select(Tratamiento).where(Tratamiento.id_tratamiento == aviso.id_tratamiento,
                                                     Tratamiento.id_clinica == aviso.id_clinica)).scalar_one_or_none()
        dosis = db.execute(select(TratamientoDosis).where(TratamientoDosis.id_dosis == aviso.id_dosis,
                                                         TratamientoDosis.id_clinica == aviso.id_clinica)).scalar_one_or_none()
        usuario = db.execute(select(Usuario).options(lazyload(Usuario.rol_rel)).where(Usuario.id_usuario == aviso.id_usuario,
                                                   Usuario.id_clinica == aviso.id_clinica)).scalar_one_or_none()
        medicamento = (db.execute(select(TratamientoMedicamento).where(
            TratamientoMedicamento.id_medicamento_plan == dosis.id_medicamento_plan,
            TratamientoMedicamento.id_clinica == aviso.id_clinica)).scalar_one_or_none() if dosis else None)
        permitido = (plan is not None and plan.estado == "ACTIVO" and _receta_valida(db, plan)
                     and dosis is not None and dosis.cancelada_en_utc is None
                     and medicamento is not None and medicamento.estado == "ACTIVO"
                     and dispositivo.activo and dispositivo.id_usuario == aviso.id_usuario
                     and usuario is not None and usuario.notificaciones_push
                     and (usuario.estado or "").upper() == "ACTIVO")
        if aviso.tipo in {"RECORDATORIO", "OMISION"} and dosis is not None and dosis.estado == "INGERIDA":
            permitido = False
        if aviso.tipo == "RECORDATORIO" and dosis is not None and now > _utc(dosis.programada_en_utc):
            permitido = False
        if aviso.tipo == "RIESGO_ABANDONO" and dosis is not None and medicamento is not None:
            recientes = db.execute(select(TratamientoDosis).where(
                TratamientoDosis.id_clinica == aviso.id_clinica,
                TratamientoDosis.id_medicamento_plan == medicamento.id_medicamento_plan,
                TratamientoDosis.cancelada_en_utc.is_(None),
                TratamientoDosis.programada_en_utc <= dosis.programada_en_utc,
            ).order_by(TratamientoDosis.programada_en_utc.desc(), TratamientoDosis.id_dosis.desc()).limit(3)).scalars().all()
            if len(recientes) < 3 or any(_puntual(item) for item in recientes):
                permitido = False
        if not permitido:
            entrega.estado = "FALLIDO"
            entrega.intentos = MAX_INTENTOS
            entrega.ultimo_error = "AVISO_NO_VIGENTE"
        else:
            entrega.intentos += 1
            try:
                token = _fernet().decrypt(dispositivo.token_cifrado.encode("ascii")).decode("utf-8")
                sender(token, aviso.titulo, aviso.mensaje, plan.id_tratamiento, aviso.id_aviso)
                entrega.estado = "ENVIADO"
                entrega.enviada_en_utc = now
                entrega.ultimo_error = None
                enviados += 1
            except Exception:
                # No almacenar errores de proveedores ni tokens; pueden contener datos sensibles.
                entrega.estado = "FALLIDO"
                entrega.ultimo_error = "ERROR_ENTREGA"
                entrega.proximo_intento_en_utc = now + timedelta(seconds=min(3600, 60 * 2 ** (entrega.intentos - 1)))
        db.flush()
        estados = db.execute(select(TratamientoEntregaPush).where(
            TratamientoEntregaPush.id_clinica == aviso.id_clinica,
            TratamientoEntregaPush.id_aviso == aviso.id_aviso)).scalars().all()
        aviso.intentos = max((item.intentos for item in estados), default=0)
        if estados and all(item.estado == "ENVIADO" for item in estados):
            aviso.estado, aviso.enviada_en_utc, aviso.ultimo_error = "ENVIADO", now, None
        elif any(item.estado == "FALLIDO" for item in estados):
            aviso.estado, aviso.ultimo_error = "FALLIDO", "ERROR_ENTREGA"
    db.flush()
    return enviados


def _usuario_sistema(db: Session, clinica_id: int):
    try:
        mapping = json.loads(settings.CU17_SYSTEM_USER_IDS_JSON)
        user_id = int(mapping[str(clinica_id)])
    except (ValueError, TypeError, KeyError):
        return None
    return db.execute(select(Usuario).options(lazyload(Usuario.rol_rel)).join(Rol, Rol.id_rol == Usuario.id_rol).where(
        Usuario.id_usuario == user_id, Usuario.id_clinica == clinica_id,
        Usuario.estado.ilike("activo"), Rol.estado.ilike("activo"), Rol.nombre.ilike("sistema"),
        ((Rol.id_clinica == clinica_id) | Rol.id_clinica.is_(None)),
    )).scalar_one_or_none()


def _reconciliar(db: Session, plan: Tratamiento, now: datetime) -> bool:
    """Persiste la transición por receta anulada con cuenta de sistema de la clínica."""
    user = _usuario_sistema(db, plan.id_clinica)
    if user is None:
        return False
    receta = db.execute(select(Receta.fecha_anulacion).where(
        Receta.id_clinica == plan.id_clinica, Receta.id_receta == plan.id_receta)).first()
    fecha = _utc(receta.fecha_anulacion) if receta and receta.fecha_anulacion else now
    plan.estado = "SUSPENDIDO_POR_RECETA"
    medicamentos = select(TratamientoMedicamento.id_medicamento_plan).where(
        TratamientoMedicamento.id_clinica == plan.id_clinica,
        TratamientoMedicamento.id_tratamiento == plan.id_tratamiento)
    db.execute(update(TratamientoDosis).where(
        TratamientoDosis.id_clinica == plan.id_clinica,
        TratamientoDosis.id_medicamento_plan.in_(medicamentos),
        TratamientoDosis.programada_en_utc >= fecha,
        TratamientoDosis.cancelada_en_utc.is_(None),
    ).values(cancelada_en_utc=fecha))
    db.add(TratamientoEvento(id_clinica=plan.id_clinica, id_tratamiento=plan.id_tratamiento,
        accion="SUSPENDER_POR_RECETA", estado_anterior="ACTIVO", estado_nuevo="SUSPENDIDO_POR_RECETA",
        id_usuario=user.id_usuario, rol_actor="SISTEMA", ocurrida_en_utc=now))
    registrar_auditoria(db, id_usuario=user.id_usuario, id_clinica=plan.id_clinica,
        tabla_afectada="tratamientos", registro_id=plan.id_tratamiento, accion="UPDATE",
        descripcion="SUSPENDER_POR_RECETA",
        datos_anteriores={"estado": "ACTIVO"},
        datos_nuevos={"estado": "SUSPENDIDO_POR_RECETA", "rol_actor": "SISTEMA"})
    db.flush()
    return True


def ejecutar_ciclo(db: Session, *, now: datetime | None = None, sender=enviar_fcm) -> dict:
    """Ejecuta un ciclo; caller confirma la transacción y programa ejecuciones periódicas."""
    from app.modules.medical_records.tratamientos.service import materializar
    now = _utc(now or _now())
    if db.bind.dialect.name == "postgresql":
        obtained = db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": 170017}).scalar()
        if not obtained:
            return {"ocupado": True, "avisos": 0, "entregas": 0, "clinicas_sin_sistema": []}
    planes = db.execute(select(Tratamiento).where(Tratamiento.estado == "ACTIVO").with_for_update(skip_locked=True)).scalars().all()
    errores, fechas_cubiertas = set(), {}
    for plan in planes:
        if not _receta_valida(db, plan):
            if not _reconciliar(db, plan, now):
                errores.add(plan.id_clinica)
            continue
        local = now.astimezone(ZoneInfo(plan.zona_horaria)).date()
        horizonte = min(plan.fecha_fin, local + timedelta(days=7))
        # Reservar siempre la ventana actual para no perder recordatorios
        # mientras se reconstruye el histórico en lotes acotados.
        if local <= horizonte:
            materializar(db, plan, max(local, plan.fecha_inicio), horizonte, now=now)
        cursor = db.execute(select(TratamientoCursor).where(
            TratamientoCursor.id_clinica == plan.id_clinica,
            TratamientoCursor.id_tratamiento == plan.id_tratamiento).with_for_update()).scalar_one_or_none()
        if cursor is None:
            cursor = TratamientoCursor(id_clinica=plan.id_clinica,
                id_tratamiento=plan.id_tratamiento, siguiente_fecha=plan.fecha_inicio)
            db.add(cursor)
            db.flush()
        if cursor.siguiente_fecha <= horizonte:
            fin = min(cursor.siguiente_fecha + timedelta(days=30), horizonte)
            materializar(db, plan, cursor.siguiente_fecha, fin, now=now)
            cursor.siguiente_fecha = fin + timedelta(days=1)
        fechas_cubiertas[(plan.id_clinica, plan.id_tratamiento)] = (cursor.siguiente_fecha, plan.zona_horaria)
    db.flush()
    creados = generar_avisos(db, now=now, fechas_cubiertas=fechas_cubiertas)
    enviados = despachar_push(db, now=now, sender=sender)
    return {"ocupado": False, "avisos": creados, "entregas": enviados,
            "clinicas_sin_sistema": sorted(errores)}
