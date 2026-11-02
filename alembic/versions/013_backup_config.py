"""Backup: tabla global backup_config (cambio backup-copias-seguridad).

Revision ID: backup01ab23cd
Revises: f7a8b9c0d1e2
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "backup01ab23cd"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backup_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hora", sa.String(length=5), server_default="02:00", nullable=False),
        sa.Column("dias_semana", postgresql.JSONB(astext_type=sa.Text()),
                  server_default='["lun", "mar", "mie", "jue", "vie", "sab", "dom"]',
                  nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("retencion_dias", sa.Integer(), server_default="7", nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO backup_config (id, hora, dias_semana, activo, retencion_dias) "
        "VALUES (1, '02:00', '[\"lun\", \"mar\", \"mie\", \"jue\", \"vie\", \"sab\", \"dom\"]', true, 7) "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("backup_config")
