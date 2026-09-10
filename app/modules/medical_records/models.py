from datetime import date, datetime
from typing import Optional
from sqlalchemy import (
    BigInteger,
    Integer,
    Column,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class Paciente(Base):
    __tablename__ = "pacientes"

    id_paciente = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    id_clinica = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("clinicas.id_clinica"), nullable=True, index=True)
    id_usuario = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("usuarios.id_usuario", ondelete="SET NULL"), unique=True, nullable=True, index=True)
    
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    ci = Column(String(20), nullable=False, index=True)
    complemento = Column(String(10), nullable=True, default="")
    fecha_nacimiento = Column(Date, nullable=False)
    genero = Column(String(10), nullable=False)  # M, F, OTRO
    
    telefono = Column(String(20), nullable=False)
    correo = Column(String(150), nullable=True)
    direccion = Column(String(255), nullable=True)
    ciudad = Column(String(100), nullable=True, default="Santa Cruz de la Sierra")
    
    tipo_sangre = Column(String(5), nullable=True)  # A+, A-, B+, B-, AB+, AB-, O+, O-
    alergias = Column(Text, nullable=True)
    antecedentes_patologicos = Column(Text, nullable=True)
    
    contacto_emergencia_nombre = Column(String(150), nullable=True)
    contacto_emergencia_telefono = Column(String(20), nullable=True)
    contacto_emergencia_parentesco = Column(String(50), nullable=True)
    
    seguro_medico = Column(String(100), nullable=True)
    numero_seguro = Column(String(50), nullable=True)
    
    estado = Column(String(20), nullable=False, default="ACTIVO", index=True)  # ACTIVO, INACTIVO, SUSPENDIDO
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    usuario = relationship("Usuario", backref="paciente_perfil", lazy="joined")

    __table_args__ = (
        UniqueConstraint("ci", "complemento", name="uq_pacientes_ci_complemento"),
    )

    @property
    def tenant_id(self):
        return self.id_clinica

    def __repr__(self) -> str:
        return f"<Paciente(id={self.id_paciente}, ci='{self.ci}', nombres='{self.nombres} {self.apellidos}')>"


# Re-export de modelos de HCE, Fichas y Documentos Clínicos para acceso canónico desde medical_records.models
from app.modules.medical_records.hce.models import HistoriaClinica, Consulta, Diagnostico  # noqa: E402, F401
from app.modules.medical_records.fichas.models import FichaClinica  # noqa: E402, F401
from app.modules.medical_records.clinical_documents.models import DocumentoClinico  # noqa: E402, F401

