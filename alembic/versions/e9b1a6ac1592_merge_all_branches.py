"""merge_all_branches

Revision ID: e9b1a6ac1592
Revises: 002_agregar_version_sesion, 002_alinear_ddl, 002_crear_medicos_especialidades, 002_crear_tabla_pacientes
Create Date: 2026-08-25 03:01:18.201798

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9b1a6ac1592'
down_revision: Union[str, Sequence[str], None] = ('002_agregar_version_sesion', '002_alinear_ddl', '002_crear_medicos_especialidades', '002_crear_tabla_pacientes')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
