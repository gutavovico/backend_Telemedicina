from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class UsuarioActivoDTO(BaseModel):
    idUsuario: int
    nombre: str
    iniciales: str

    model_config = ConfigDict(from_attributes=True)


class PatientSummaryDTO(BaseModel):
    idPaciente: int
    nombreCompleto: str
    identificacionId: str
    inicialesAvatar: str
    seguroProveedor: str
    seguroPoliza: str

    model_config = ConfigDict(from_attributes=True)


class AppointmentDetailsDTO(BaseModel):
    idCita: int
    nombreMedico: str
    especialidad: str
    rangoFechas: str
    horaTeleconsulta: str
    modalidad: str = "TELEMEDICINA"
    estado: str = "CONFIRMADA"

    model_config = ConfigDict(from_attributes=True)


class DoctorProfileSummaryDTO(BaseModel):
    idMedico: int
    nombreCompleto: str
    cargoEtiqueta: str = "Su Médico"
    biografia: str
    fotoUrl: Optional[str] = None
    estadoDisponibilidad: str = "DISPONIBLE"

    model_config = ConfigDict(from_attributes=True)


class ChatMessageDTO(BaseModel):
    idMensaje: int
    idRemitente: int
    nombreRemitente: str
    rolRemitente: str
    contenido: str
    horaDisplay: str
    avatarUrl: Optional[str] = None
    esPropio: bool = False
    leido: bool = False
    adjuntoNombre: Optional[str] = None
    adjuntoTamano: Optional[str] = None
    adjuntoUrl: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SendChatMessageCommand(BaseModel):
    idCita: int
    contenido: str = Field(..., min_length=1, max_length=1000, description="Texto del mensaje")
    adjuntoNombre: Optional[str] = None
    adjuntoTamano: Optional[str] = None
    adjuntoUrl: Optional[str] = None


class TeleconsultaViewDTO(BaseModel):
    nombreClinica: str
    usuarioActivo: UsuarioActivoDTO
    paciente: PatientSummaryDTO
    cita: AppointmentDetailsDTO
    medico: DoctorProfileSummaryDTO
    mensajes: List[ChatMessageDTO] = []

    model_config = ConfigDict(from_attributes=True)
