"""crear tabla fichas clinicas cu09

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-10 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea la tabla fichas_clinicas con soporte para correlativos únicos y esquemas dinámicos JSONB."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS fichas_clinicas (
            id_ficha VARCHAR(36) PRIMARY KEY,
            id_clinica BIGINT NOT NULL REFERENCES clinicas(id_clinica) ON DELETE RESTRICT,
            correlativo VARCHAR(50) NOT NULL,
            id_paciente BIGINT NOT NULL REFERENCES pacientes(id_paciente) ON DELETE RESTRICT,
            id_medico BIGINT NOT NULL REFERENCES medicos(id_medico) ON DELETE RESTRICT,
            id_servicio BIGINT NULL REFERENCES servicios_medicos(id_servicio) ON DELETE SET NULL,
            id_especialidad BIGINT NULL REFERENCES especialidades(id_especialidad) ON DELETE SET NULL,
            id_cita BIGINT NULL REFERENCES citas(id_cita) ON DELETE SET NULL,
            fecha_emision TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            fecha_atencion DATE NOT NULL,
            hora_inicio VARCHAR(10) NOT NULL,
            hora_fin VARCHAR(10) NOT NULL,
            motivo_consulta TEXT NOT NULL,
            signos_vitales JSONB DEFAULT '{}'::jsonb,
            secciones_dinamicas JSONB DEFAULT '{}'::jsonb,
            codigo_cie10 VARCHAR(30) NULL,
            diagnostico_descripcion TEXT NULL,
            id_diagnostico BIGINT NULL REFERENCES diagnosticos(id_diagnostico) ON DELETE SET NULL,
            notas_evolucion TEXT NULL,
            estado VARCHAR(30) DEFAULT 'EMITIDA' NOT NULL,
            motivo_cancelacion TEXT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT uq_fichas_clinica_correlativo UNIQUE (id_clinica, correlativo),
            CONSTRAINT uq_fichas_medico_slot UNIQUE (id_clinica, id_medico, fecha_atencion, hora_inicio)
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_fichas_clinica_paciente ON fichas_clinicas(id_clinica, id_paciente);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fichas_clinica_medico ON fichas_clinicas(id_clinica, id_medico, fecha_atencion);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fichas_clinica_estado ON fichas_clinicas(id_clinica, estado);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fichas_correlativo ON fichas_clinicas(correlativo);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fichas_clinicas CASCADE;")
