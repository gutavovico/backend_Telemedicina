"""ampliar tabla citas cu25

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-09-10 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Amplía la tabla citas para soportar CU25 (Gestionar Consulta Médica):
    - id_especialidad: FK a especialidades (SET NULL).
    - fecha_cita, hora_inicio, hora_fin: campos para asignación temporal de turnos.
    - tipo_consulta, notas: modalidad y observaciones.
    - created_at, updated_at: auditoría temporal.
    """
    op.execute("""
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS id_especialidad BIGINT REFERENCES especialidades(id_especialidad) ON DELETE SET NULL;
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS fecha_cita DATE;
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS hora_inicio VARCHAR(10);
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS hora_fin VARCHAR(10);
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS tipo_consulta VARCHAR(20) DEFAULT 'TELEMEDICINA';
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS notas TEXT;
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_citas_id_especialidad ON citas(id_especialidad)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_citas_fecha_cita ON citas(fecha_cita)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_citas_estado ON citas(estado)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_citas_estado")
    op.execute("DROP INDEX IF EXISTS idx_citas_fecha_cita")
    op.execute("DROP INDEX IF EXISTS idx_citas_id_especialidad")
    op.execute("""
        ALTER TABLE citas DROP COLUMN IF EXISTS updated_at;
        ALTER TABLE citas DROP COLUMN IF EXISTS created_at;
        ALTER TABLE citas DROP COLUMN IF EXISTS notas;
        ALTER TABLE citas DROP COLUMN IF EXISTS tipo_consulta;
        ALTER TABLE citas DROP COLUMN IF EXISTS hora_fin;
        ALTER TABLE citas DROP COLUMN IF EXISTS hora_inicio;
        ALTER TABLE citas DROP COLUMN IF EXISTS fecha_cita;
        ALTER TABLE citas DROP COLUMN IF EXISTS id_especialidad;
    """)
