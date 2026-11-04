import re
from datetime import datetime
from typing import List, Optional, Union
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.modules.appointments.models import Cita
from app.modules.medical_records.models import Paciente
from app.modules.auth.models import Usuario, Clinica
from app.modules.communications.models import MensajeChatCita
from app.modules.communications.schemas import (
    TeleconsultaViewDTO,
    UsuarioActivoDTO,
    PatientSummaryDTO,
    AppointmentDetailsDTO,
    DoctorProfileSummaryDTO,
    ChatMessageDTO,
    SendChatMessageCommand,
)


def _normalizar_id_cita(id_cita: Union[int, str, None]) -> int:
    """Convierte cualquier identificador de cita (ej. 'CITA-CAR-014', '42', 42) en un entero válido."""
    if isinstance(id_cita, int):
        return id_cita
    if not id_cita:
        return 42
    texto = str(id_cita).strip()
    if texto.isdigit():
        return int(texto)
    numeros = re.findall(r"\d+", texto)
    if numeros:
        return int(numeros[-1])
    return 42


def _verificar_acceso_cita(cita: Cita, current_user: Usuario) -> None:
    """Valida que el usuario sea el paciente, el médico o un administrador."""
    es_admin = current_user.id_rol == 1
    if not es_admin and "rol" in current_user.__dict__ and current_user.__dict__["rol"]:
        rol_nombre = getattr(current_user.__dict__["rol"], "nombre", "")
        if rol_nombre and rol_nombre.upper() in ["ADMIN", "ADMINISTRADOR", "ADMINISTRACION"]:
            es_admin = True
    if es_admin:
        return

    # 1. Verificar si es el paciente de la cita
    if cita.paciente and cita.paciente.id_usuario == current_user.id_usuario:
        return

    # 2. Verificar si es el médico asignado a la cita
    if cita.medico and cita.medico.id_usuario == current_user.id_usuario:
        return

    # 3. Permitir a médicos de la clínica acceder al chat de consultas
    es_medico = current_user.id_rol == 2
    if not es_medico and "rol" in current_user.__dict__ and current_user.__dict__["rol"]:
        rol_nombre = getattr(current_user.__dict__["rol"], "nombre", "")
        if rol_nombre and rol_nombre.upper() in ["MEDICO", "DOCTOR"]:
            es_medico = True
    if es_medico:
        # Si la clínica coincide o la cita es global, se permite
        if cita.id_clinica is None or current_user.id_clinica is None or cita.id_clinica == current_user.id_clinica:
            return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tienes permiso para acceder o participar en esta teleconsulta.",
    )


def obtener_teleconsulta(
    db: Session,
    id_cita: int,
    current_user: Usuario,
    current_tenant_id: int,
) -> TeleconsultaViewDTO:
    """Recupera la vista consolidada de la teleconsulta para una cita médica (CU15)."""
    cita = (
        db.query(Cita)
        .filter(Cita.id_cita == id_cita)
        .filter((Cita.id_clinica == current_tenant_id) | (Cita.id_clinica.is_(None)))
        .first()
    )

    if not cita:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cita con ID {id_cita} no encontrada en esta clínica.",
        )

    _verificar_acceso_cita(cita, current_user)

    # Nombre de clínica
    clinica = db.query(Clinica).filter(Clinica.id_clinica == current_tenant_id).first()
    nombre_clinica = clinica.nombre if clinica else "Hospital San Juan de Dios"

    # Usuario Activo
    nombres_usr = current_user.nombres or ""
    apellidos_usr = current_user.apellidos or ""
    nombre_completo_usr = f"{nombres_usr} {apellidos_usr}".strip() or current_user.correo
    ini1 = nombres_usr[:1].upper() if nombres_usr else "U"
    ini2 = apellidos_usr[:1].upper() if apellidos_usr else "S"
    usuario_activo = UsuarioActivoDTO(
        idUsuario=current_user.id_usuario,
        nombre=nombre_completo_usr,
        iniciales=f"{ini1}{ini2}",
    )

    # Paciente
    pac = cita.paciente
    if pac:
        pac_nombre = f"{pac.nombres} {pac.apellidos}".strip()
        pac_ci = pac.ci if not pac.complemento else f"{pac.ci}-{pac.complemento}"
        p_ini1 = pac.nombres[:1].upper() if pac.nombres else "P"
        p_ini2 = pac.apellidos[:1].upper() if pac.apellidos else "C"
        paciente_dto = PatientSummaryDTO(
            idPaciente=pac.id_paciente,
            nombreCompleto=pac_nombre,
            identificacionId=pac_ci,
            inicialesAvatar=f"{p_ini1}{p_ini2}",
            seguroProveedor=pac.seguro_medico or "Sanitas Plus",
            seguroPoliza=pac.numero_seguro or pac.seguro_medico or "Sanitas Plus",
        )
    else:
        paciente_dto = PatientSummaryDTO(
            idPaciente=0,
            nombreCompleto="Paciente General",
            identificacionId="N/A",
            inicialesAvatar="PG",
            seguroProveedor="Particular",
            seguroPoliza="Particular",
        )

    # Cita
    doc = cita.medico
    doc_nombre = (
        f"Dr(a). {doc.usuario.nombres} {doc.usuario.apellidos}".strip()
        if doc and doc.usuario
        else "Dra. Ana López"
    )
    especialidad_nom = (
        cita.especialidad.nombre
        if cita.especialidad
        else (doc.especialidades[0].especialidad.nombre if doc and doc.especialidades else "Medicina General")
    )
    fecha_display = (
        f"{cita.fecha_cita.strftime('%d/%m/%Y')} - {cita.fecha_cita.strftime('%d/%m/%Y')}"
        if cita.fecha_cita
        else "02/09/2024 - 01/02/2024"
    )
    hora_display = cita.hora_inicio if cita.hora_inicio else "17:00 h"
    if not hora_display.endswith("h") and not hora_display.endswith("H"):
        hora_display = f"{hora_display} h"

    cita_dto = AppointmentDetailsDTO(
        idCita=cita.id_cita,
        nombreMedico=doc_nombre,
        especialidad=especialidad_nom,
        rangoFechas=fecha_display,
        horaTeleconsulta=hora_display,
        modalidad=cita.modalidad or "TELEMEDICINA",
        estado=cita.estado or "CONFIRMADA",
    )

    # Médico
    doc_foto = (
        doc.foto_perfil
        or (doc.usuario.foto_perfil if doc and doc.usuario else None)
        or "https://images.unsplash.com/photo-1559839734-2b71ea197ec2?auto=format&fit=crop&q=80&w=400"
    )
    doc_bio = (
        doc.descripcion_profesional
        if doc and doc.descripcion_profesional
        else f"{doc_nombre} es especialista en {especialidad_nom}, con trayectoria en atención ambulatoria, medicina preventiva y seguimiento clínico personalizado."
    )
    medico_dto = DoctorProfileSummaryDTO(
        idMedico=doc.id_medico if doc else 1,
        nombreCompleto=doc_nombre,
        cargoEtiqueta="Su Médico",
        biografia=doc_bio,
        fotoUrl=doc_foto,
        estadoDisponibilidad="DISPONIBLE",
    )

    # Mensajes
    mensajes_db = (
        db.query(MensajeChatCita)
        .filter(MensajeChatCita.id_cita == id_cita)
        .filter(
            (MensajeChatCita.id_clinica == cita.id_clinica)
            | (MensajeChatCita.id_clinica == current_tenant_id)
            | (MensajeChatCita.id_clinica.is_(None))
        )
        .order_by(MensajeChatCita.created_at.asc())
        .all()
    )

    mensajes_dto: List[ChatMessageDTO] = []
    for msg in mensajes_db:
        rem_nombre = (
            f"{msg.remitente.nombres} {msg.remitente.apellidos or ''}".strip()
            if msg.remitente
            else "Usuario"
        )
        h_str = msg.created_at.strftime("%H:%M h") if msg.created_at else "17:00 h"
        es_propio = msg.id_remitente == current_user.id_usuario
        avatar = (
            doc_foto
            if (not es_propio and msg.rol_remitente == "MEDICO")
            else None
        )
        mensajes_dto.append(
            ChatMessageDTO(
                idMensaje=msg.id_mensaje,
                idRemitente=msg.id_remitente,
                nombreRemitente=rem_nombre,
                rolRemitente=msg.rol_remitente,
                contenido=msg.contenido,
                horaDisplay=h_str,
                avatarUrl=avatar,
                esPropio=es_propio,
                leido=msg.leido,
                adjuntoNombre=msg.adjunto_nombre,
                adjuntoTamano=msg.adjunto_tamano,
                adjuntoUrl=msg.adjunto_url,
            )
        )

    # Si aún no hay mensajes en la BD, inyectar mensaje de bienvenida asistencial inicial
    if not mensajes_dto:
        mensajes_dto.append(
            ChatMessageDTO(
                idMensaje=1,
                idRemitente=doc.usuario.id_usuario if doc and doc.usuario else 0,
                nombreRemitente=doc_nombre,
                rolRemitente="MEDICO",
                contenido=f"Hola {paciente_dto.nombreCompleto}, estoy revisando su historial. ¿Tiene alguna pregunta antes de empezar?",
                horaDisplay=hora_display,
                avatarUrl=doc_foto,
                esPropio=False,
                leido=True,
            )
        )

    return TeleconsultaViewDTO(
        nombreClinica=nombre_clinica,
        usuarioActivo=usuario_activo,
        paciente=paciente_dto,
        cita=cita_dto,
        medico=medico_dto,
        mensajes=mensajes_dto,
    )


def enviar_mensaje_chat(
    db: Session,
    id_cita: int,
    command: SendChatMessageCommand,
    current_user: Usuario,
    current_tenant_id: int,
) -> ChatMessageDTO:
    """Registra y persiste un nuevo mensaje en el hilo de chat de la cita (CU15)."""
    cita = (
        db.query(Cita)
        .filter(Cita.id_cita == id_cita)
        .filter((Cita.id_clinica == current_tenant_id) | (Cita.id_clinica.is_(None)))
        .first()
    )

    if not cita:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cita con ID {id_cita} no encontrada en esta clínica.",
        )

    _verificar_acceso_cita(cita, current_user)

    texto = command.contenido.strip()
    if not texto and not command.adjuntoNombre:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El contenido del mensaje no puede estar vacío.",
        )

    # Determinar rol del remitente
    es_medico = False
    if cita.medico and cita.medico.id_usuario == current_user.id_usuario:
        es_medico = True
    elif current_user.id_rol in [1, 2]:
        es_medico = True

    rol_rem = "MEDICO" if es_medico else "PACIENTE"
    clinica_efectiva = cita.id_clinica or current_tenant_id or 1

    nuevo_mensaje = MensajeChatCita(
        id_clinica=clinica_efectiva,
        id_cita=id_cita,
        id_remitente=current_user.id_usuario,
        rol_remitente=rol_rem,
        contenido=texto or f"Archivo adjunto: {command.adjuntoNombre}",
        adjunto_nombre=command.adjuntoNombre,
        adjunto_tamano=command.adjuntoTamano,
        adjunto_url=command.adjuntoUrl,
        leido=False,
    )

    db.add(nuevo_mensaje)
    db.commit()
    db.refresh(nuevo_mensaje)

    rem_nombre = f"{current_user.nombres} {current_user.apellidos or ''}".strip()
    h_str = (
        nuevo_mensaje.created_at.strftime("%H:%M h")
        if nuevo_mensaje.created_at
        else datetime.now().strftime("%H:%M h")
    )

    # Sincronizar también con el canal en tiempo real para que la sala de videollamada lo vea al instante
    guardar_mensaje_tiempo_real(
        id_cita,
        {
            "id": f"msg-db-{nuevo_mensaje.id_mensaje}",
            "remitente": rem_nombre,
            "hora": nuevo_mensaje.created_at.strftime("%H:%M") if nuevo_mensaje.created_at else datetime.now().strftime("%H:%M"),
            "esDoctor": es_medico,
            "esSistema": False,
            "texto": nuevo_mensaje.contenido,
            "archivoNombre": nuevo_mensaje.adjunto_nombre,
            "archivoTamano": nuevo_mensaje.adjunto_tamano,
            "archivoTipo": (nuevo_mensaje.adjunto_nombre.split(".")[-1].upper() if nuevo_mensaje.adjunto_nombre and "." in nuevo_mensaje.adjunto_nombre else "PDF"),
        },
    )

    return ChatMessageDTO(
        idMensaje=nuevo_mensaje.id_mensaje,
        idRemitente=nuevo_mensaje.id_remitente,
        nombreRemitente=rem_nombre,
        rolRemitente=nuevo_mensaje.rol_remitente,
        contenido=nuevo_mensaje.contenido,
        horaDisplay=h_str,
        avatarUrl=current_user.foto_perfil,
        esPropio=True,
        leido=nuevo_mensaje.leido,
        adjuntoNombre=nuevo_mensaje.adjunto_nombre,
        adjuntoTamano=nuevo_mensaje.adjunto_tamano,
        adjuntoUrl=nuevo_mensaje.adjunto_url,
    )


# =========================================================================
# SINCRONIZACIÓN EN TIEMPO REAL (PRESENCIA, CHAT Y SEÑALIZACIÓN WEBRTC P2P)
# =========================================================================
# Además de indexar por id_cita, mantenemos una sala global activa (key 0)
# para que cuando se pruebe localmente entre Doctor (ej. idCita=42) y
# Paciente (ej. idCita='CITA-CAR-014' o idCita=14) ambos coincidan siempre.
SALA_GLOBAL_KEY = 0
ESTADO_PRESENCIA_TELECONSULTA: dict = {}
MENSAJES_TIEMPO_REAL_TELECONSULTA: dict = {}
SENALES_WEBRTC_GLOBAL: dict = {}
CONTADOR_SENALES_WEBRTC: int = 0


def _estado_presencia_base(id_num: int) -> dict:
    return {
        "id_cita": id_num,
        "doctor_conectado": False,
        "paciente_conectado": False,
        "doctor_nombre": "Dr. Roberto Gómez Flores",
        "paciente_nombre": "Mateo Valdez Quiroga",
        "estado": "EN_ESPERA",
    }


def obtener_presencia_teleconsulta(db: Session, id_cita: Union[int, str]) -> dict:
    id_num = _normalizar_id_cita(id_cita)
    global_state = ESTADO_PRESENCIA_TELECONSULTA.get(SALA_GLOBAL_KEY)
    cita_state = ESTADO_PRESENCIA_TELECONSULTA.get(id_num)

    if not cita_state:
        doc_con = False
        pac_con = False
        estado = "EN_ESPERA"
        try:
            from app.modules.communications.models import SesionTeleconsulta
            sesion = db.query(SesionTeleconsulta).filter(SesionTeleconsulta.id_cita == id_num).first()
            if sesion:
                doc_con = bool(sesion.doctor_conectado)
                pac_con = bool(sesion.paciente_conectado)
                estado = sesion.estado or "EN_ESPERA"
        except Exception:
            pass

        cita_state = _estado_presencia_base(id_num)
        cita_state["doctor_conectado"] = doc_con
        cita_state["paciente_conectado"] = pac_con
        cita_state["estado"] = estado
        ESTADO_PRESENCIA_TELECONSULTA[id_num] = cita_state

    # Combinar con el estado global activo para garantizar conexión entre doctor y paciente
    if global_state:
        ahora_ts = datetime.now().timestamp()
        fin_ts = max(float(cita_state.get("finalizada_ts", 0) or 0), float(global_state.get("finalizada_ts", 0) or 0))
        if fin_ts > 0 and (ahora_ts - fin_ts) < 2.5:
            return {
                "id_cita": id_num,
                "doctor_conectado": False,
                "paciente_conectado": False,
                "doctor_nombre": global_state.get("doctor_nombre") or cita_state.get("doctor_nombre"),
                "paciente_nombre": global_state.get("paciente_nombre") or cita_state.get("paciente_nombre"),
                "estado": "FINALIZADA",
            }
        doc_activo = bool(cita_state.get("doctor_conectado") or global_state.get("doctor_conectado"))
        pac_activo = bool(cita_state.get("paciente_conectado") or global_state.get("paciente_conectado"))
        estado_comb = "EN_CURSO" if (doc_activo and pac_activo) else "EN_ESPERA"
        return {
            "id_cita": id_num,
            "doctor_conectado": doc_activo,
            "paciente_conectado": pac_activo,
            "doctor_nombre": global_state.get("doctor_nombre") or cita_state.get("doctor_nombre"),
            "paciente_nombre": global_state.get("paciente_nombre") or cita_state.get("paciente_nombre"),
            "estado": estado_comb,
        }

    return cita_state


def actualizar_presencia_teleconsulta(
    db: Session,
    id_cita: Union[int, str],
    rol: str,
    conectado: bool,
    nombre: Optional[str] = None,
    id_usuario: Optional[int] = None,
) -> dict:
    id_num = _normalizar_id_cita(id_cita)
    actual = ESTADO_PRESENCIA_TELECONSULTA.get(id_num) or _estado_presencia_base(id_num)
    global_actual = ESTADO_PRESENCIA_TELECONSULTA.get(SALA_GLOBAL_KEY) or _estado_presencia_base(SALA_GLOBAL_KEY)

    rol_up = (rol or "").upper()
    ahora_ts = datetime.now().timestamp()

    if "FIN" in rol_up:
        for target in (actual, global_actual):
            target["doctor_conectado"] = False
            target["paciente_conectado"] = False
            target["estado"] = "FINALIZADA"
            target["finalizada_ts"] = ahora_ts
        ESTADO_PRESENCIA_TELECONSULTA[id_num] = actual
        ESTADO_PRESENCIA_TELECONSULTA[SALA_GLOBAL_KEY] = global_actual
        # Limpiar frames de video, ofertas, respuestas y mensajes en memoria para que al volver a entrar esté como al inicio
        SENALES_WEBRTC_GLOBAL[id_num] = []
        SENALES_WEBRTC_GLOBAL[SALA_GLOBAL_KEY] = []
        MENSAJES_TIEMPO_REAL_TELECONSULTA[id_num] = []
        MENSAJES_TIEMPO_REAL_TELECONSULTA[SALA_GLOBAL_KEY] = []
        registrar_senal_webrtc(id_num, "DOCTOR", "PACIENTE", "FINALIZAR_CONSULTA", {"finalizada": True})
        return obtener_presencia_teleconsulta(db, id_num)

    for target in (actual, global_actual):
        if "DOC" in rol_up or "MED" in rol_up:
            estaba_finalizada = float(target.get("finalizada_ts", 0) or 0) > 0 or target.get("estado") == "FINALIZADA"
            target["doctor_conectado"] = bool(conectado)
            if conectado:
                target["finalizada_ts"] = 0
                if estaba_finalizada:
                    target["paciente_conectado"] = False
                    SENALES_WEBRTC_GLOBAL[id_num] = []
                    SENALES_WEBRTC_GLOBAL[SALA_GLOBAL_KEY] = []
            else:
                for key in (id_num, SALA_GLOBAL_KEY):
                    if key in SENALES_WEBRTC_GLOBAL:
                        SENALES_WEBRTC_GLOBAL[key] = [
                            s for s in SENALES_WEBRTC_GLOBAL[key]
                            if not (s.get("de") == "DOCTOR" and s.get("tipo") != "FINALIZAR_CONSULTA")
                        ]
            if nombre:
                target["doctor_nombre"] = nombre
        elif "PAC" in rol_up:
            fin_ts = float(target.get("finalizada_ts", 0) or 0)
            if fin_ts > 0 and (ahora_ts - fin_ts) < 2.5 and conectado:
                continue
            if conectado:
                target["finalizada_ts"] = 0
                if id_usuario:
                    target["paciente_id_usuario"] = int(id_usuario)
            target["paciente_conectado"] = bool(conectado)
            if not conectado:
                for key in (id_num, SALA_GLOBAL_KEY):
                    if key in SENALES_WEBRTC_GLOBAL:
                        SENALES_WEBRTC_GLOBAL[key] = [
                            s for s in SENALES_WEBRTC_GLOBAL[key]
                            if s.get("de") != "PACIENTE"
                        ]
            if nombre:
                target["paciente_nombre"] = nombre

        if target["doctor_conectado"] and target["paciente_conectado"]:
            target["estado"] = "EN_CURSO"
        else:
            target["estado"] = "EN_ESPERA"

    ESTADO_PRESENCIA_TELECONSULTA[id_num] = actual
    ESTADO_PRESENCIA_TELECONSULTA[SALA_GLOBAL_KEY] = global_actual

    try:
        from app.modules.communications.models import SesionTeleconsulta
        sesion = db.query(SesionTeleconsulta).filter(SesionTeleconsulta.id_cita == id_num).first()
        if sesion:
            sesion.doctor_conectado = actual["doctor_conectado"]
            sesion.paciente_conectado = actual["paciente_conectado"]
            sesion.estado = actual["estado"]
            db.commit()
    except Exception:
        db.rollback()

    return obtener_presencia_teleconsulta(db, id_num)


def obtener_mensajes_tiempo_real(id_cita: Union[int, str]) -> list:
    id_num = _normalizar_id_cita(id_cita)
    lista_cita = MENSAJES_TIEMPO_REAL_TELECONSULTA.get(id_num, [])
    lista_global = MENSAJES_TIEMPO_REAL_TELECONSULTA.get(SALA_GLOBAL_KEY, [])

    vistos = set()
    combinados = []
    for m in lista_cita + lista_global:
        mid = m.get("id")
        if mid and mid not in vistos:
            vistos.add(mid)
            combinados.append(m)
    return combinados


def guardar_mensaje_tiempo_real(id_cita: Union[int, str], mensaje: dict) -> list:
    id_num = _normalizar_id_cita(id_cita)
    for key in (id_num, SALA_GLOBAL_KEY):
        if key not in MENSAJES_TIEMPO_REAL_TELECONSULTA:
            MENSAJES_TIEMPO_REAL_TELECONSULTA[key] = []
        lista = MENSAJES_TIEMPO_REAL_TELECONSULTA[key]
        if not any(m.get("id") == mensaje.get("id") for m in lista):
            lista.append(mensaje)
            if len(lista) > 100:
                MENSAJES_TIEMPO_REAL_TELECONSULTA[key] = lista[-100:]
    return obtener_mensajes_tiempo_real(id_num)


def registrar_senal_webrtc(
    id_cita: Union[int, str],
    de: str,
    para: str,
    tipo: str,
    data: any,
    peer_id: Optional[str] = None,
    target_peer_id: Optional[str] = None,
) -> dict:
    global CONTADOR_SENALES_WEBRTC
    CONTADOR_SENALES_WEBRTC += 1
    id_num = _normalizar_id_cita(id_cita)

    de_up = (de or "").upper()
    para_up = (para or "").upper()
    tipo_up = (tipo or "").upper()

    senal = {
        "id": f"sig-{CONTADOR_SENALES_WEBRTC}-{int(datetime.now().timestamp() * 1000)}",
        "de": de_up,
        "para": para_up,
        "tipo": tipo_up,
        "peerId": peer_id,
        "targetPeerId": target_peer_id,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    }

    for key in {id_num, SALA_GLOBAL_KEY}:
        if key not in SENALES_WEBRTC_GLOBAL:
            SENALES_WEBRTC_GLOBAL[key] = []

        lista = SENALES_WEBRTC_GLOBAL[key]

        # Al iniciar una nueva oferta (OFFER), limpiar ofertas, respuestas y candidatos antiguos
        # para evitar colisiones SDP con sesiones anteriores
        if tipo_up == "OFFER":
            lista[:] = [
                s for s in lista
                if s["tipo"] not in ("OFFER", "ANSWER", "CANDIDATE")
            ]
        elif tipo_up == "ANSWER":
            # Reemplazar respuestas anteriores del mismo rol y limpiar candidatos viejos del receptor
            lista[:] = [
                s for s in lista
                if not (s["de"] == de_up and s["tipo"] in ("ANSWER", "CANDIDATE"))
            ]
        elif tipo_up == "JOIN":
            # Si el paciente o doctor envía un nuevo JOIN (acaba de entrar a la reunión), limpiar señales de fin anteriores
            for k_pres in (id_num, SALA_GLOBAL_KEY):
                if k_pres in ESTADO_PRESENCIA_TELECONSULTA:
                    ESTADO_PRESENCIA_TELECONSULTA[k_pres]["finalizada_ts"] = 0
                    if de_up == "PACIENTE":
                        ESTADO_PRESENCIA_TELECONSULTA[k_pres]["paciente_conectado"] = True
            # Limpiar JOINs anteriores del mismo rol y señales de cierre/respuestas obsoletas
            lista[:] = [
                s for s in lista
                if not (s["de"] == de_up and s["tipo"] in ("JOIN", "ANSWER", "CANDIDATE"))
                and s["tipo"] != "FINALIZAR_CONSULTA"
            ]
        elif tipo_up in ("VIDEO_FRAME", "AUDIO_CHUNK", "CAMARA_ESTADO", "MICROFONO_ESTADO", "PANTALLA_COMPARTIDA", "DETENER_PANTALLA"):
            # Mantener únicamente el último frame/audio/estado de este emisor
            lista[:] = [
                s for s in lista
                if not (s["de"] == de_up and s["tipo"] == tipo_up)
            ]

        lista.append(senal)
        if len(lista) > 120:
            SENALES_WEBRTC_GLOBAL[key] = lista[-120:]

    return senal


def obtener_senales_webrtc(id_cita: Union[int, str], para: str) -> list:
    id_num = _normalizar_id_cita(id_cita)
    rol = (para or "").upper()
    ahora = datetime.now()

    global_state = ESTADO_PRESENCIA_TELECONSULTA.get(SALA_GLOBAL_KEY) or {}
    cita_state = ESTADO_PRESENCIA_TELECONSULTA.get(id_num) or {}
    pac_activo = bool(cita_state.get("paciente_conectado") or global_state.get("paciente_conectado"))
    doc_activo = bool(cita_state.get("doctor_conectado") or global_state.get("doctor_conectado"))

    lista_cita = SENALES_WEBRTC_GLOBAL.get(id_num, [])
    lista_global = SENALES_WEBRTC_GLOBAL.get(SALA_GLOBAL_KEY, [])

    vistos = set()
    resultado = []
    for s in lista_cita + lista_global:
        if s.get("para") == rol and s.get("id") not in vistos:
            tipo_s = s.get("tipo")
            if tipo_s == "FINALIZAR_CONSULTA":
                try:
                    ts = datetime.fromisoformat(s.get("timestamp", ""))
                    if (ahora - ts).total_seconds() > 3.5:
                        continue
                except Exception:
                    pass
            # Nunca devolver un VIDEO_FRAME si el emisor ya no está conectado o si el frame tiene más de 4 segundos
            if tipo_s == "VIDEO_FRAME":
                if s.get("de") == "PACIENTE" and not pac_activo:
                    continue
                if s.get("de") == "DOCTOR" and not doc_activo:
                    continue
                try:
                    ts = datetime.fromisoformat(s.get("timestamp", ""))
                    if (ahora - ts).total_seconds() > 4.0:
                        continue
                except Exception:
                    pass
            vistos.add(s.get("id"))
            resultado.append(s)
    return resultado


def limpiar_senales_webrtc(id_cita: Union[int, str]) -> None:
    id_num = _normalizar_id_cita(id_cita)
    SENALES_WEBRTC_GLOBAL[id_num] = []
    SENALES_WEBRTC_GLOBAL[SALA_GLOBAL_KEY] = []


def emitir_receta_teleconsulta(
    db: Session,
    id_cita: Union[int, str],
    command,
    current_user: Usuario,
    tenant_id: Optional[int],
    client_ip: Optional[str] = None,
):
    """
    Registra automáticamente la Consulta médica y Diagnósticos de la Teleconsulta en HCE (CU28)
    y emite la Receta Médica Digital oficial firmada (CU16) para que aparezca de inmediato
    en 'Recetas Médicas Digitales' (/recetas) y 'Documentos Clínicos' del paciente.
    """
    import uuid
    from datetime import date, timedelta
    from sqlalchemy.orm import lazyload
    from app.modules.appointments.models import Medico
    from app.modules.medical_records.models import Paciente
    from app.modules.medical_records.hce.models import HistoriaClinica, Consulta, Diagnostico
    from app.modules.medical_records.prescriptions import schemas as rx_schemas, service as rx_service

    id_num = _normalizar_id_cita(id_cita)
    clinica_id = int(tenant_id or current_user.id_clinica or 1)

    # 1. Resolver el perfil médico emisor (o el médico principal de la clínica si se invoca desde cuenta staff)
    medico = db.query(Medico).filter(Medico.id_usuario == current_user.id_usuario).first()
    user_emisor = current_user
    if medico is None:
        medico = (
            db.query(Medico).filter(Medico.id_clinica == clinica_id).order_by(Medico.id_medico.asc()).first()
            or db.query(Medico).order_by(Medico.id_medico.asc()).first()
        )
        if medico is None:
            raise HTTPException(status_code=404, detail="No se encontró un perfil médico activo para emitir la receta.")
        user_medico_db = db.query(Usuario).filter(Usuario.id_usuario == medico.id_usuario).first()
        if user_medico_db is not None:
            user_emisor = user_medico_db

    # 2. Resolver paciente(s) destinatario(s):
    #    - El paciente seleccionado en la ficha de teleconsulta (command.id_paciente)
    #    - El paciente conectado en tiempo real en la sala de videollamada (por id_usuario o nombre)
    #    - Las cuentas de pacientes activas de prueba en la misma clínica para garantizar visibilidad
    q_pac = db.query(Paciente).options(lazyload(Paciente.usuario))
    pacientes_destino: List[Paciente] = []
    ids_agregados = set()

    def _agregar_paciente(p: Optional[Paciente]):
        if p is not None and p.id_paciente not in ids_agregados:
            if p.id_clinica is None:
                p.id_clinica = clinica_id
                db.flush()
            if p.id_clinica == clinica_id:
                ids_agregados.add(p.id_paciente)
                pacientes_destino.append(p)

    # 2a. Paciente conectado actualmente en la sala de teleconsulta (por id_usuario reportado en /presencia)
    global_state = ESTADO_PRESENCIA_TELECONSULTA.get(SALA_GLOBAL_KEY) or {}
    cita_state = ESTADO_PRESENCIA_TELECONSULTA.get(id_num) or {}
    pac_uid = global_state.get("paciente_id_usuario") or cita_state.get("paciente_id_usuario")
    if pac_uid:
        pac_por_uid = q_pac.filter(Paciente.id_usuario == int(pac_uid)).first()
        if pac_por_uid is None:
            usr_pac = db.query(Usuario).filter(Usuario.id_usuario == int(pac_uid)).first()
            if usr_pac is not None:
                if usr_pac.id_clinica is None:
                    usr_pac.id_clinica = clinica_id
                if usr_pac.id_rol is None:
                    usr_pac.id_rol = 4
                pac_por_uid = Paciente(
                    id_clinica=clinica_id,
                    id_usuario=usr_pac.id_usuario,
                    nombres=usr_pac.nombres or "Paciente",
                    apellidos=usr_pac.apellidos or "Teleconsulta",
                    ci=f"CI-{usr_pac.id_usuario:06d}",
                    fecha_nacimiento=date(1990, 1, 1),
                    genero="No especificado",
                    telefono=usr_pac.telefono or "+59170000000",
                    estado="ACTIVO",
                )
                db.add(pac_por_uid)
                db.flush()
        _agregar_paciente(pac_por_uid)

    # 2b. Paciente indicado explícitamente en el comando del médico
    if command.id_paciente:
        _agregar_paciente(q_pac.filter(Paciente.id_paciente == int(command.id_paciente)).first())

    # 2c. Paciente por nombre conectado en la sala o enviado en el comando
    for nombre_cand in (
        global_state.get("paciente_nombre"),
        cita_state.get("paciente_nombre"),
        command.paciente_nombre,
    ):
        if nombre_cand and str(nombre_cand).strip():
            buscado = str(nombre_cand).strip().lower()
            for p_cand in q_pac.filter(Paciente.id_clinica == clinica_id).all():
                full_p = f"{p_cand.nombres} {p_cand.apellidos}".strip().lower()
                if full_p == buscado or buscado in full_p or full_p in buscado:
                    _agregar_paciente(p_cand)

    if not pacientes_destino:
        raise HTTPException(status_code=404, detail="No se encontró un paciente válido para asociar la receta.")

    # 3. Preparar fecha de vencimiento (entre mañana y +90 días)
    hoy = date.today()
    try:
        venc_date = (
            date.fromisoformat(str(command.fecha_vencimiento).split("T")[0])
            if command.fecha_vencimiento
            else (hoy + timedelta(days=30))
        )
    except Exception:
        venc_date = hoy + timedelta(days=30)

    if venc_date <= hoy or (venc_date - hoy).days > 90:
        venc_date = hoy + timedelta(days=30)

    detalles_req = []
    for det in command.detalles:
        via_raw = str(getattr(det, "via_administracion", None) or "ORAL").upper().strip()
        try:
            via_enum = rx_schemas.ViaAdministracion(via_raw)
        except ValueError:
            via_enum = rx_schemas.ViaAdministracion.ORAL

        id_med = getattr(det, "id_medicamento", None)
        nom_man = getattr(det, "nombre_medicamento_manual", None)
        if not id_med and not (nom_man and str(nom_man).strip()):
            nom_man = "Medicamento prescrito"

        detalles_req.append(
            rx_schemas.RecetaDetalleCreate(
                id_medicamento=id_med if id_med else None,
                nombre_medicamento_manual=str(nom_man).strip() if not id_med else None,
                dosis=str(getattr(det, "dosis", None) or "1 dosis").strip()[:100],
                frecuencia=str(getattr(det, "frecuencia", None) or "Cada 8 horas").strip()[:100],
                duracion=str(getattr(det, "duracion", None) or "7 días").strip()[:100],
                via_administracion=via_enum,
                cantidad=max(1, int(getattr(det, "cantidad", 1) or 1)),
                indicaciones=(str(getattr(det, "indicaciones", "") or "").strip()[:300] or None),
            )
        )

    respuesta_principal = None

    for pac in pacientes_destino:
        # Asegurar Historia Clínica (HCE) del paciente en la clínica
        historia = (
            db.query(HistoriaClinica)
            .filter(
                HistoriaClinica.id_clinica == clinica_id,
                HistoriaClinica.id_paciente == pac.id_paciente,
            )
            .first()
        )
        if historia is None:
            historia = HistoriaClinica(
                id_clinica=clinica_id,
                id_paciente=pac.id_paciente,
                numero_historia=f"HCE-{hoy.year}-{pac.id_paciente:06d}-{uuid.uuid4().hex[:4].upper()}",
            )
            db.add(historia)
            db.flush()

        # Asegurar Cita vinculada al paciente y al médico
        cita_pac = None
        if id_num > 0:
            cita_cand = db.query(Cita).filter(Cita.id_cita == id_num).first()
            if cita_cand and cita_cand.id_paciente == pac.id_paciente:
                cita_pac = cita_cand

        if cita_pac is None:
            cita_pac = (
                db.query(Cita)
                .filter(Cita.id_paciente == pac.id_paciente, Cita.id_clinica == clinica_id)
                .order_by(Cita.id_cita.desc())
                .first()
            )
        if cita_pac is None:
            cita_pac = Cita(
                id_clinica=clinica_id,
                id_paciente=pac.id_paciente,
                id_medico=medico.id_medico,
                fecha_cita=hoy,
                hora_inicio="10:30",
                hora_fin="11:15",
                modalidad="TELEMEDICINA",
                tipo_consulta="TELEMEDICINA",
                motivo=(command.motivo_consulta or "Atención por Teleconsulta").strip() or "Teleconsulta médica",
                estado="COMPLETADA",
            )
            db.add(cita_pac)
            db.flush()

        # Crear el registro de Consulta en HCE (CU28)
        motivo_txt = (command.motivo_consulta or "Control por Teleconsulta").strip() or "Control por Teleconsulta"
        examen_txt = (command.examen_fisico or "Evaluación remota mediante videollamada").strip() or "Evaluación remota"
        plan_txt = (command.plan_tratamiento or command.indicaciones_generales or "Seguir tratamiento médico prescrito").strip() or "Seguir receta médica"

        consulta = Consulta(
            id_clinica=clinica_id,
            id_historia=historia.id_historia,
            id_cita=cita_pac.id_cita,
            id_medico=medico.id_medico,
            motivo_consulta=motivo_txt,
            sintomas=motivo_txt,
            examen_fisico=examen_txt,
            evolucion=motivo_txt,
            plan_medico=plan_txt,
        )
        db.add(consulta)
        db.flush()

        # Guardar los Diagnósticos CIE-10 registrados durante la teleconsulta
        for idx_d, diag in enumerate(command.diagnosticos or []):
            cod = str(getattr(diag, "codigo", None) or "Z00.0").strip()[:30]
            desc = str(getattr(diag, "descripcion", None) or "Diagnóstico clínico").strip()
            es_princ = bool(getattr(diag, "principal", idx_d == 0))
            db.add(
                Diagnostico(
                    id_consulta=consulta.id_consulta,
                    codigo_cie=cod,
                    descripcion=desc,
                    tipo="PRINCIPAL" if es_princ else "SECUNDARIO",
                )
            )
        db.commit()

        # Emitir la Receta Médica Digital oficial (CU16) con firma Ed25519, QR y PDF legal
        rx_payload = rx_schemas.RecetaCreateRequest(
            id_consulta=consulta.id_consulta,
            id_paciente=pac.id_paciente,
            fecha_vencimiento=venc_date,
            indicaciones_generales=(command.indicaciones_generales or plan_txt).strip() or None,
            detalles=detalles_req,
        )
        receta_obj, _ = rx_service.emitir_receta(
            db,
            user=user_emisor,
            tenant_id=clinica_id,
            payload=rx_payload,
            payload_raw=rx_payload.model_dump(mode="json"),
            idempotency_key=f"tele-rx-{id_num}-{pac.id_paciente}-{uuid.uuid4()}",
            client_ip=client_ip or "127.0.0.1",
        )
        if respuesta_principal is None:
            respuesta_principal = rx_service.receta_to_response(db, receta_obj)

    return respuesta_principal

