"""merge enriqSPR3 con main

Revision ID: 62b0d532ee0a
Revises: f4a5b6c7d8e9, cu34_catalogo_016, temp_credentials_019
Create Date: 2026-11-04 17:42:38.238283

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62b0d532ee0a'
down_revision: Union[str, Sequence[str], None] = ('f4a5b6c7d8e9', 'cu34_catalogo_016', 'temp_credentials_019')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
