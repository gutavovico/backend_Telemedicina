"""crear_tablas_base

Revision ID: 002b_crear_tablas_base
Revises: 002_alinear_ddl
Create Date: 2026-10-02 00:00:00.000000

Motivo: las revisiones 003_crear_tabla_citas y 004_crear_documentos_clinicos
referencian las tablas ``pacientes``, ``medicos`` y ``especialidades``, pero
ninguna migracion del repositorio las creaba. Sin esta revision, la cadena no
era reproducible sobre una base de datos nueva.

La definicion replica el esquema desplegado en Neon (verificado via
information_schema.pg). Todo es idempotente (CREATE ... IF NOT EXISTS), por lo
que no altera bases existentes. La columna ``pacientes.id_clinica`` NO se crea
aqui a proposito: la agrega 004_crear_documentos_clinicos de forma idempotente,
manteniendo la division de responsabilidades original.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '002b_crear_tablas_base'
down_revision: Union[str, Sequence[str], None] = '002_alinear_ddl'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. pacientes
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS pacientes (
            id_paciente BIGSERIAL PRIMARY KEY,
            id_usuario BIGINT REFERENCES usuarios(id_usuario),
            nombres VARCHAR(100) NOT NULL,
            apellidos VARCHAR(100) NOT NULL,
            ci VARCHAR(20) NOT NULL,
            complemento VARCHAR(10) DEFAULT '',
            fecha_nacimiento DATE NOT NULL,
            genero VARCHAR(10) NOT NULL,
            telefono VARCHAR(20) NOT NULL,
            correo VARCHAR(150),
            direccion VARCHAR(255),
            ciudad VARCHAR(100) DEFAULT 'Santa Cruz de la Sierra',
            tipo_sangre VARCHAR(5),
            alergias TEXT,
            antecedentes_patologicos TEXT,
            contacto_emergencia_nombre VARCHAR(150),
            contacto_emergencia_telefono VARCHAR(20),
            contacto_emergencia_parentesco VARCHAR(50),
            seguro_medico VARCHAR(100),
            numero_seguro VARCHAR(50),
            estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_pacientes_ci_complemento UNIQUE (ci, complemento)
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_pacientes_id_usuario ON pacientes (id_usuario)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pacientes_ci ON pacientes (ci)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pacientes_estado ON pacientes (estado)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pacientes_id_paciente ON pacientes (id_paciente)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pacientes_nombres_apellidos "
        "ON pacientes (nombres, apellidos)"
    )

    # ------------------------------------------------------------------ #
    # 2. medicos
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS medicos (
            id_medico BIGSERIAL PRIMARY KEY,
            id_usuario BIGINT NOT NULL REFERENCES usuarios(id_usuario),
            matricula_profesional VARCHAR(30) NOT NULL,
            descripcion_profesional TEXT,
            experiencia TEXT,
            foto_perfil VARCHAR(500),
            estado VARCHAR(20) NOT NULL DEFAULT 'activo',
            fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_medicos_id_usuario UNIQUE (id_usuario),
            CONSTRAINT uq_medicos_matricula_profesional UNIQUE (matricula_profesional)
        )
    """)

    # ------------------------------------------------------------------ #
    # 3. especialidades
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS especialidades (
            id_especialidad BIGSERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            descripcion TEXT,
            estado VARCHAR(20) NOT NULL DEFAULT 'activo',
            CONSTRAINT uq_especialidades_nombre UNIQUE (nombre)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS especialidades")
    op.execute("DROP TABLE IF EXISTS medicos")
    op.execute("DROP TABLE IF EXISTS pacientes")
