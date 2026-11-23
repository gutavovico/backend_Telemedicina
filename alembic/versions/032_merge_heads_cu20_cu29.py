"""Converge las dos cabezas resultantes de integrar CU20 y CU29 en la rama 031.

Después de esta revisión `alembic upgrade head` vuelve a ser determinista:
ambas ramas (`cu29_vinculacion_sede_031` y `cu20_main_merge_031`) convergen
en una única cabeza. No modifica el esquema.
"""

from alembic import op  # noqa: F401  (se mantiene por convención de Alembic)

revision = "merge_heads_cu20_cu29_032"
down_revision = ("cu29_vinculacion_sede_031", "cu20_main_merge_031")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
