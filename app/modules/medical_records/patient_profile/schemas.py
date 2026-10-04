from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class PacienteBase(BaseModel):
    id_clinica: Optional[int] = None
    tenant_id: Optional[str] = None
    nombres: str = Field(..., min_length=2, max_length=100, examples=["Carlos Alberto"])
    apellidos: str = Field(..., min_length=2, max_length=100, examples=["Mamani Terrazas"])
    ci: str = Field(..., min_length=3, max_length=20, examples=["7891234"])
    complemento: Optional[str] = Field("", max_length=10, examples=["LP"])
    fecha_nacimiento: date = Field(..., examples=["1990-05-15"])
    genero: str = Field(..., examples=["M"])  # M, F, OTRO
    telefono: str = Field(..., min_length=6, max_length=20, examples=["+591 71234567"])
    correo: Optional[EmailStr] = Field(None, examples=["carlos.mamani@email.com"])
    direccion: Optional[str] = Field(None, max_length=255, examples=["Av. Banzer 4to Anillo"])
    ciudad: Optional[str] = Field("Santa Cruz de la Sierra", max_length=100, examples=["Santa Cruz de la Sierra"])
    tipo_sangre: Optional[str] = Field(None, max_length=5, examples=["O+"])
    alergias: Optional[str] = Field(None, examples=["Penicilina, AINEs"])
    antecedentes_patologicos: Optional[str] = Field(None, examples=["Hipertensión arterial controlada"])
    contacto_emergencia_nombre: Optional[str] = Field(None, max_length=150, examples=["Maria Terrazas"])
    contacto_emergencia_telefono: Optional[str] = Field(None, max_length=20, examples=["+591 79876543"])
    contacto_emergencia_parentesco: Optional[str] = Field(None, max_length=50, examples=["Madre"])
    seguro_medico: Optional[str] = Field(None, max_length=100, examples=["Seguro Universitario"])
    numero_seguro: Optional[str] = Field(None, max_length=50, examples=["SU-98765"])

    @field_validator("fecha_nacimiento")
    @classmethod
    def validar_fecha_nacimiento(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("La fecha de nacimiento no puede ser posterior a la fecha actual.")
        return v

    @field_validator("genero")
    @classmethod
    def validar_genero(cls, v: str) -> str:
        genero_norm = v.strip().upper()
        if genero_norm not in ["M", "F", "OTRO"]:
            raise ValueError("El género debe ser 'M', 'F' u 'OTRO'.")
        return genero_norm

    @field_validator("tipo_sangre")
    @classmethod
    def validar_tipo_sangre(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "":
            return None
        tipo_norm = v.strip().upper()
        if tipo_norm not in ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]:
            raise ValueError("El tipo de sangre debe ser uno de: A+, A-, B+, B-, AB+, AB-, O+, O-.")
        return tipo_norm


class PacienteCreateRequest(PacienteBase):
    id_usuario: Optional[int] = Field(None, examples=[12])


class PacienteUpdateRequest(BaseModel):
    id_clinica: Optional[int] = None
    nombres: Optional[str] = Field(None, min_length=2, max_length=100)
    apellidos: Optional[str] = Field(None, min_length=2, max_length=100)
    telefono: Optional[str] = Field(None, min_length=6, max_length=20)
    correo: Optional[EmailStr] = None
    direccion: Optional[str] = Field(None, max_length=255)
    ciudad: Optional[str] = Field(None, max_length=100)
    tipo_sangre: Optional[str] = None
    alergias: Optional[str] = None
    antecedentes_patologicos: Optional[str] = None
    contacto_emergencia_nombre: Optional[str] = Field(None, max_length=150)
    contacto_emergencia_telefono: Optional[str] = Field(None, max_length=20)
    contacto_emergencia_parentesco: Optional[str] = Field(None, max_length=50)
    seguro_medico: Optional[str] = Field(None, max_length=100)
    numero_seguro: Optional[str] = Field(None, max_length=50)
    estado: Optional[str] = Field(None, examples=["ACTIVO"])

    @field_validator("tipo_sangre")
    @classmethod
    def validar_tipo_sangre(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "":
            return None
        tipo_norm = v.strip().upper()
        if tipo_norm not in ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]:
            raise ValueError("El tipo de sangre debe ser uno de: A+, A-, B+", "B-", "AB+", "AB-", "O+", "O-.")
        return tipo_norm

    @field_validator("estado")
    @classmethod
    def validar_estado(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        estado_norm = v.strip().upper()
        if estado_norm not in ["ACTIVO", "INACTIVO", "SUSPENDIDO"]:
            raise ValueError("El estado debe ser 'ACTIVO', 'INACTIVO' o 'SUSPENDIDO'.")
        return estado_norm


class PacienteProfilePatchRequest(BaseModel):
    telefono: Optional[str] = Field(None, min_length=6, max_length=20, examples=["+591 70011223"])
    correo: Optional[EmailStr] = Field(None, examples=["carlos.nuevo@email.com"])
    direccion: Optional[str] = Field(None, max_length=255, examples=["Barrio Equipetrol Norte"])
    ciudad: Optional[str] = Field(None, max_length=100, examples=["Santa Cruz de la Sierra"])
    contacto_emergencia_nombre: Optional[str] = Field(None, max_length=150, examples=["Roberto Mamani"])
    contacto_emergencia_telefono: Optional[str] = Field(None, max_length=20, examples=["+591 76655443"])
    contacto_emergencia_parentesco: Optional[str] = Field(None, max_length=50, examples=["Hermano"])


class PacienteResponse(BaseModel):
    id_paciente: int
    id_clinica: Optional[int] = None
    tenant_id: Optional[str] = None
    id_usuario: Optional[int] = None
    nombres: str
    apellidos: str
    ci: str
    complemento: Optional[str] = ""
    fecha_nacimiento: date
    genero: str
    telefono: str
    correo: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = "Santa Cruz de la Sierra"
    tipo_sangre: Optional[str] = None
    alergias: Optional[str] = None
    antecedentes_patologicos: Optional[str] = None
    contacto_emergencia_nombre: Optional[str] = None
    contacto_emergencia_telefono: Optional[str] = None
    contacto_emergencia_parentesco: Optional[str] = None
    seguro_medico: Optional[str] = None
    numero_seguro: Optional[str] = None
    estado: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PacientePaginationResponse(BaseModel):
    items: List[PacienteResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
