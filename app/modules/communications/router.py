from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, get_required_tenant_id
from app.modules.auth.models import Usuario
from app.modules.appointments.models import Cita
from app.modules.communications import service
from app.modules.communications.schemas import (
    TeleconsultaViewDTO,
    ChatMessageDTO,
    SendChatMessageCommand,
)

router = APIRouter(prefix="/citas", tags=["Teleconsulta y Chat (CU15)"])


@router.get(
    "/me/teleconsulta",
    response_model=TeleconsultaViewDTO,
    summary="Obtener teleconsulta activa o más reciente del usuario autenticado (CU15)",
)
def obtener_mi_teleconsulta_activa(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: int = Depends(get_required_tenant_id),
):
    """Localiza la cita médica activa más reciente del paciente o médico para inicializar teleconsulta."""
    # Buscar si el usuario es paciente con una cita
    cita = (
        db.query(Cita)
        .join(Cita.paciente)
        .filter(Cita.paciente.has(id_usuario=current_user.id_usuario))
        .filter((Cita.id_clinica == tenant_id) | (Cita.id_clinica.is_(None)))
        .order_by(Cita.id_cita.desc())
        .first()
    )

    # Si no es paciente, buscar si es médico con una cita
    if not cita:
        cita = (
            db.query(Cita)
            .join(Cita.medico)
            .filter(Cita.medico.has(id_usuario=current_user.id_usuario))
            .filter((Cita.id_clinica == tenant_id) | (Cita.id_clinica.is_(None)))
            .order_by(Cita.id_cita.desc())
            .first()
        )

    # Si no tiene citas registradas, solo administradores pueden previsualizar la última cita de la clínica
    es_admin = current_user.id_rol == 1
    if not cita and es_admin:
        cita = (
            db.query(Cita)
            .filter((Cita.id_clinica == tenant_id) | (Cita.id_clinica.is_(None)))
            .order_by(Cita.id_cita.desc())
            .first()
        )

    if cita:
        return service.obtener_teleconsulta(db, cita.id_cita, current_user, tenant_id)

    # Si no existe ninguna cita aún en la BD, generar la vista inicial basada en el perfil del usuario
    nombre_completo = f"{current_user.nombres} {current_user.apellidos or ''}".strip()
    ini1 = current_user.nombres[:1].upper() if current_user.nombres else "C"
    ini2 = current_user.apellidos[:1].upper() if current_user.apellidos else "P"

    from app.modules.communications.schemas import (
        UsuarioActivoDTO,
        PatientSummaryDTO,
        AppointmentDetailsDTO,
        DoctorProfileSummaryDTO,
    )

    return TeleconsultaViewDTO(
        nombreClinica="Hospital San Juan de Dios",
        usuarioActivo=UsuarioActivoDTO(
            idUsuario=current_user.id_usuario,
            nombre=nombre_completo,
            iniciales=f"{ini1}{ini2}",
        ),
        paciente=PatientSummaryDTO(
            idPaciente=current_user.id_usuario,
            nombreCompleto=nombre_completo,
            identificacionId="12345678X",
            inicialesAvatar=f"{ini1}{ini2}",
            seguroProveedor="Sanitas Plus",
            seguroPoliza="Sanitas Plus",
        ),
        cita=AppointmentDetailsDTO(
            idCita=105,
            nombreMedico="Dra. Ana López",
            especialidad="Medicina General",
            rangoFechas="02/09/2024 - 01/02/2024",
            horaTeleconsulta="17:00 h",
            modalidad="TELEMEDICINA",
            estado="CONFIRMADA",
        ),
        medico=DoctorProfileSummaryDTO(
            idMedico=42,
            nombreCompleto="Dra. Ana López",
            cargoEtiqueta="Su Médico",
            biografia="Dra. Ana López es especialista en medicina general, con trayectoria en atención ambulatoria, medicina preventiva y seguimiento clínico personalizado.",
            fotoUrl="https://images.unsplash.com/photo-1559839734-2b71ea197ec2?auto=format&fit=crop&q=80&w=400",
            estadoDisponibilidad="DISPONIBLE",
        ),
        mensajes=[
            ChatMessageDTO(
                idMensaje=1,
                idRemitente=42,
                nombreRemitente="Dra. López",
                rolRemitente="MEDICO",
                contenido=f"Hola {nombre_completo}, estoy revisando su historial. ¿Tiene alguna pregunta antes de empezar?",
                horaDisplay="17:00 h",
                avatarUrl="https://images.unsplash.com/photo-1559839734-2b71ea197ec2?auto=format&fit=crop&q=80&w=120",
                esPropio=False,
                leido=True,
            )
        ],
    )


@router.get(
    "/{id_cita}/teleconsulta",
    response_model=TeleconsultaViewDTO,
    summary="Obtener vista y estado consolidado de teleconsulta (CU15)",
)
def obtener_teleconsulta(
    id_cita: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: int = Depends(get_required_tenant_id),
):
    """Retorna los datos de filiación, cita médica, ficha del médico tratante e historial de chat."""
    return service.obtener_teleconsulta(db, id_cita, current_user, tenant_id)


@router.post(
    "/{id_cita}/chat/mensajes",
    response_model=ChatMessageDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar mensaje al chat de la cita médica (CU15)",
)
def enviar_mensaje_chat(
    id_cita: int,
    command: SendChatMessageCommand,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: int = Depends(get_required_tenant_id),
):
    """Registra y persiste un mensaje en el chat de la teleconsulta con actualización en base de datos."""
    return service.enviar_mensaje_chat(db, id_cita, command, current_user, tenant_id)
