"""merge_heads_cu10_and_cu15

Revision ID: 11411f333d08
Revises: 007_crear_catalogo_examenes, e3f4a5b6c7d8
Create Date: 2026-10-04 20:30:57.211853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11411f333d08'
down_revision: Union[str, Sequence[str], None] = ('007_crear_catalogo_examenes', 'e3f4a5b6c7d8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
