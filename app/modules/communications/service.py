from datetime import datetime
from typing import List, Optional
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
