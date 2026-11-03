"""Unir las migraciones independientes de CU17 y copias de seguridad.

Revision ID: cu17_backup_merge_015
Revises: 014_operaciones_dosis_cu17, backup01ab23cd
"""

from typing import Sequence, Union


revision: str = "cu17_backup_merge_015"
down_revision: Union[str, Sequence[str], None] = (
    "014_operaciones_dosis_cu17",
    "backup01ab23cd",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
