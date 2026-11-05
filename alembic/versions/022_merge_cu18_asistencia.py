"""Converge la revisión recuperada de CU18 con la cabeza actual.

Revision ID: merge_cu18_asistencia_022
Revises: cu18_asistencia_017, cu06_servicios_clinica_021

Neon había registrado ``cu18_asistencia_017`` como última revisión, pero el
archivo correspondiente no estaba en el repositorio. La revisión recuperada
partía de ``cu34_catalogo_016`` y quedó en una rama distinta de la cabeza
actual. Este merge point vuelve a dejar una única cabeza en el grafo.
"""
from alembic import op


revision = "merge_cu18_asistencia_022"
down_revision = ("cu18_asistencia_017", "cu06_servicios_clinica_021")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
