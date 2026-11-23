"""Converge la rama CU20 (notificaciones multicanal) con main (030_merge_cu29_cu07_cu33).

Esta revisión no modifica el esquema. Existe únicamente para que Alembic mantenga
una única cabeza después de integrar CU20 sobre `cu29_cu07_cu33_merge_030`.
"""

revision = "cu20_main_merge_031"
down_revision = ("cu29_cu07_cu33_merge_030", "cu20_notificaciones_017")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
