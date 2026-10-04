"""agregar version de sesion

Revision ID: 002_agregar_version_sesion
Revises: 001_crear_tabla_usuarios
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_agregar_version_sesion"
down_revision: Union[str, None] = "001_crear_tabla_usuarios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column("token_version", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "token_version")
