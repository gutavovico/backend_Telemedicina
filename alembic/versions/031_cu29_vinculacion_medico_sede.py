"""CU29: habilitar la asignación de sedes por vínculo médico-entidad.

Depende del head que ya integra CU33 (`cu29_cu07_cu33_merge_030`), por lo que
`sedes` y su clave primaria `sedes.id` existen cuando esta revisión se aplica.
La tabla se apoya en el catálogo de CU33 y no crea uno alternativo.

Revision ID: cu29_vinculacion_sede_031
Revises: cu29_cu07_cu33_merge_030
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "cu29_vinculacion_sede_031"
down_revision: Union[str, Sequence[str], None] = "cu29_cu07_cu33_merge_030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vinculacion_medico_sede",
        sa.Column("id_vinculacion", sa.BigInteger(), nullable=False),
        sa.Column("id_sede", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id_vinculacion"],
            ["vinculaciones_medico_entidad.id_vinculacion"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["id_sede"], ["sedes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id_vinculacion", "id_sede"),
    )
    op.create_index(
        "ix_vinculacion_medico_sede_id_sede",
        "vinculacion_medico_sede",
        ["id_sede"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vinculacion_medico_sede_id_sede", table_name="vinculacion_medico_sede"
    )
    op.drop_table("vinculacion_medico_sede")
