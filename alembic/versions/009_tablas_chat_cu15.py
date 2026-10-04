"""Crear tablas y columnas para CU15 Teleconsulta y Chat de Cita Médica

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
Create Date: 2026-10-03 05:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Asegurar discriminador de clínica / tenant_id en la tabla citas
    op.execute("""
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS id_clinica BIGINT REFERENCES clinicas(id_clinica) ON DELETE CASCADE;
        UPDATE citas
        SET id_clinica = (SELECT id_clinica FROM medicos WHERE medicos.id_medico = citas.id_medico LIMIT 1)
        WHERE id_clinica IS NULL;
        CREATE INDEX IF NOT EXISTS idx_citas_id_clinica ON citas(id_clinica);
    """)

    # 2. Crear tabla mensajes_chat_cita para CU15
    op.execute("""
        CREATE TABLE IF NOT EXISTS mensajes_chat_cita (
            id_mensaje BIGSERIAL PRIMARY KEY,
            id_clinica BIGINT NOT NULL REFERENCES clinicas(id_clinica) ON DELETE CASCADE,
            id_cita BIGINT NOT NULL REFERENCES citas(id_cita) ON DELETE CASCADE,
            id_remitente BIGINT NOT NULL REFERENCES usuarios(id_usuario) ON DELETE RESTRICT,
            rol_remitente VARCHAR(20) NOT NULL DEFAULT 'PACIENTE',
            contenido TEXT NOT NULL,
            leido BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_chat_cita_tenant ON mensajes_chat_cita (id_clinica, id_cita, created_at ASC);
        CREATE INDEX IF NOT EXISTS idx_chat_remitente ON mensajes_chat_cita (id_remitente);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mensajes_chat_cita;")
    op.execute("DROP INDEX IF EXISTS idx_citas_id_clinica;")
    op.execute("ALTER TABLE citas DROP COLUMN IF EXISTS id_clinica;")
