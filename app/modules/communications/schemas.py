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


class PresenciaTeleconsultaDTO(BaseModel):
    id_cita: int
    doctor_conectado: bool
    paciente_conectado: bool
    doctor_nombre: Optional[str] = None
    paciente_nombre: Optional[str] = None
    estado: str = 'EN_ESPERA'

    model_config = ConfigDict(from_attributes=True)


class ActualizarPresenciaCommand(BaseModel):
    rol: str
    conectado: bool
    nombre: Optional[str] = None


class MensajeRealtimeDTO(BaseModel):
    id: str
    remitente: str
    hora: str
    esDoctor: bool
    esSistema: Optional[bool] = False
    texto: Optional[str] = None
    archivoNombre: Optional[str] = None
    archivoTamano: Optional[str] = None
    archivoTipo: Optional[str] = None
    archivoUrl: Optional[str] = None


class WebrtcSignalCommand(BaseModel):
    de: str
    para: str
    tipo: str
    peerId: Optional[str] = None
    targetPeerId: Optional[str] = None
    data: Optional[dict] = None


class WebrtcSignalDTO(BaseModel):
    id: str
    de: str
    para: str
    tipo: str
    peerId: Optional[str] = None
    targetPeerId: Optional[str] = None
    data: Optional[dict] = None
    timestamp: str


class DiagnosticoTeleconsultaItem(BaseModel):
    codigo: str = "Z00.0"
    descripcion: str
    principal: bool = False


class DetalleRecetaTeleconsultaItem(BaseModel):
    id_medicamento: Optional[int] = None
    nombre_medicamento_manual: Optional[str] = None
    dosis: str
    frecuencia: str
    duracion: str
    via_administracion: str = "ORAL"
    cantidad: int = 1
    indicaciones: Optional[str] = None


class EmitirRecetaTeleconsultaCommand(BaseModel):
    id_paciente: Optional[int] = None
    paciente_nombre: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    indicaciones_generales: Optional[str] = None
    motivo_consulta: Optional[str] = None
    examen_fisico: Optional[str] = None
    plan_tratamiento: Optional[str] = None
    diagnosticos: List[DiagnosticoTeleconsultaItem] = []
    detalles: List[DetalleRecetaTeleconsultaItem] = []

