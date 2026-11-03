"""Persistencia de planes y tomas CU17; las recetas originales no se modifican."""
from sqlalchemy import (BigInteger, CheckConstraint, Column, Date, DateTime,
                        ForeignKey, Index, Integer, JSON, String, Text,
                        UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base

ID = BigInteger().with_variant(Integer, "sqlite")
JSON_VALUE = JSONB().with_variant(JSON(), "sqlite")


class Tratamiento(Base):
    __tablename__ = "tratamientos"
    id_tratamiento = Column(ID, primary_key=True, autoincrement=True)
    id_clinica = Column(ID, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_consulta = Column(ID, ForeignKey("consultas.id_consulta"), nullable=False)
    id_receta = Column(ID, ForeignKey("recetas.id_receta"), nullable=True)
    id_diagnostico = Column(ID, ForeignKey("diagnosticos.id_diagnostico"), nullable=False)
    id_paciente = Column(ID, ForeignKey("pacientes.id_paciente"), nullable=False)
    id_medico = Column(ID, ForeignKey("medicos.id_medico"), nullable=False)
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    zona_horaria = Column(String(100), nullable=False)
    estado = Column(String(30), nullable=False, default="ACTIVO")
    notas = Column(Text, nullable=True)
    motivo_cierre = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("id_clinica", "id_receta", name="uq_tratamiento_clinica_receta"),
        CheckConstraint("fecha_fin >= fecha_inicio", name="ck_tratamiento_fechas"),
        CheckConstraint("estado IN ('ACTIVO','FINALIZADO','SUSPENDIDO_POR_RECETA')", name="ck_tratamiento_estado"),
        Index("ix_tratamiento_paciente", "id_clinica", "id_paciente", "estado"),
        Index("ix_tratamiento_medico", "id_clinica", "id_medico", "estado"),
        Index("uq_tratamiento_consulta_sin_receta", "id_clinica", "id_consulta", unique=True,
              postgresql_where=id_receta.is_(None), sqlite_where=id_receta.is_(None)),
    )


class TratamientoMedicamento(Base):
    __tablename__ = "tratamiento_medicamentos"
    id_medicamento_plan = Column(ID, primary_key=True, autoincrement=True)
    id_clinica = Column(ID, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_tratamiento = Column(ID, ForeignKey("tratamientos.id_tratamiento"), nullable=False)
    id_receta_detalle = Column(ID, ForeignKey("receta_detalle.id_receta_detalle"), nullable=False)
    medicamento_nombre = Column(String(200), nullable=False)
    dosis = Column(String(100), nullable=False)
    via_administracion = Column(String(30), nullable=False)
    frecuencia_texto_receta = Column(String(100), nullable=False)
    duracion_texto_receta = Column(String(100), nullable=False)
    indicaciones = Column(Text, nullable=True)
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    horas_locales = Column(JSON_VALUE, nullable=False)
    estado = Column(String(20), nullable=False, default="ACTIVO")
    suspendido_desde = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("id_clinica", "id_tratamiento", "id_receta_detalle", name="uq_tratamiento_medicamento_detalle"),
        CheckConstraint("fecha_fin >= fecha_inicio", name="ck_tratamiento_medicamento_fechas"),
        CheckConstraint("estado IN ('ACTIVO','SUSPENDIDO')", name="ck_tratamiento_medicamento_estado"),
        Index("ix_tratamiento_medicamento_plan", "id_clinica", "id_tratamiento"),
    )


class TratamientoDosis(Base):
    __tablename__ = "tratamiento_dosis"
    id_dosis = Column(ID, primary_key=True, autoincrement=True)
    id_clinica = Column(ID, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_medicamento_plan = Column(ID, ForeignKey("tratamiento_medicamentos.id_medicamento_plan"), nullable=False)
    programada_en_utc = Column(DateTime(timezone=True), nullable=False)
    estado = Column(String(20), nullable=False, default="PENDIENTE")
    efectiva_en_utc = Column(DateTime(timezone=True), nullable=True)
    registrada_en_utc = Column(DateTime(timezone=True), nullable=True)
    cancelada_en_utc = Column(DateTime(timezone=True), nullable=True)
    alertas_evaluadas_en_utc = Column(DateTime(timezone=True), nullable=True)
    nota = Column(Text, nullable=True)
    generacion = Column(BigInteger().with_variant(Integer(), "sqlite"), nullable=False, server_default="1", default=1)
    __table_args__ = (
        UniqueConstraint("id_clinica", "id_medicamento_plan", "programada_en_utc", name="uq_tratamiento_dosis_hora"),
        CheckConstraint("estado IN ('PENDIENTE','INGERIDA','OMITIDA','POSPUESTA')", name="ck_tratamiento_dosis_estado"),
        Index("ix_tratamiento_dosis_programada", "id_clinica", "programada_en_utc", "estado"),
        Index("ix_tratamiento_dosis_alertas", "id_clinica", "alertas_evaluadas_en_utc", "programada_en_utc"),
    )


class TratamientoEvento(Base):
    __tablename__ = "tratamiento_eventos"
    id_evento = Column(ID, primary_key=True, autoincrement=True)
    id_clinica = Column(ID, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_tratamiento = Column(ID, ForeignKey("tratamientos.id_tratamiento"), nullable=False)
    id_dosis = Column(ID, ForeignKey("tratamiento_dosis.id_dosis"), nullable=True)
    id_medicamento_plan = Column(ID, ForeignKey("tratamiento_medicamentos.id_medicamento_plan"), nullable=True)
    accion = Column(String(50), nullable=False)
    estado_anterior = Column(String(30), nullable=True)
    estado_nuevo = Column(String(30), nullable=True)
    id_usuario = Column(ID, ForeignKey("usuarios.id_usuario"), nullable=False)
    rol_actor = Column(String(100), nullable=False)
    direccion_ip = Column(String(45), nullable=True)
    nota = Column(Text, nullable=True)
    efectiva_en_utc = Column(DateTime(timezone=True), nullable=True)
    ocurrida_en_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    idempotencia_hash = Column(String(64), nullable=True)
    request_hash = Column(String(64), nullable=True)
    respuesta_json = Column(JSON_VALUE, nullable=True)
    __table_args__ = (
        UniqueConstraint("id_clinica", "id_usuario", "id_dosis", "idempotencia_hash", name="uq_tratamiento_evento_idempotencia"),
        Index("ix_tratamiento_evento_plan", "id_clinica", "id_tratamiento", "ocurrida_en_utc"),
    )


class TratamientoOperacionDosis(Base):
    __tablename__ = "tratamiento_operaciones_dosis"
    id_operacion = Column(ID, primary_key=True, autoincrement=True)
    id_clinica = Column(ID, ForeignKey("clinicas.id_clinica"), nullable=False)
    id_tratamiento = Column(ID, ForeignKey("tratamientos.id_tratamiento"), nullable=False)
    id_dosis = Column(ID, ForeignKey("tratamiento_dosis.id_dosis"), nullable=False)
    id_usuario = Column(ID, ForeignKey("usuarios.id_usuario"), nullable=False)
    idempotencia_hash = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    generacion = Column(BigInteger().with_variant(Integer(), "sqlite"), nullable=False, server_default="1", default=1)
    estado = Column(String(20), nullable=False, default="EN_CURSO")
    respuesta_json = Column(JSON_VALUE, nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("id_clinica", "id_usuario", "id_dosis", "idempotencia_hash", name="uq_tratamiento_operacion_idempotencia"),
        CheckConstraint("estado IN ('EN_CURSO','CONFIRMADA','RECHAZADA')", name="ck_tratamiento_operacion_estado"),
        Index("uq_op_dosis_activa", "id_clinica", "id_dosis", unique=True,
              postgresql_where=text("estado = 'EN_CURSO'"), sqlite_where=text("estado = 'EN_CURSO'")),
        Index("ix_tratamiento_operacion_dosis", "id_clinica", "id_dosis"),
    )
