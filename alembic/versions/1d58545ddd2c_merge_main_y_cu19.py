"""merge main y CU19

Revision ID: 1d58545ddd2c
Revises: a1b2c3d4e5f6, cu17_backup_merge_015
Create Date: 2026-11-03 13:26:49.038822

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d58545ddd2c'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f6', 'cu17_backup_merge_015')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
