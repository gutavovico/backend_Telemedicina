"""Normaliza el aislamiento multitenant de perfiles médicos (CU04).

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""
from alembic import op
import sqlalchemy as sa


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable durante la transición: los perfiles heredados se completan con
    # la clínica del usuario. Las operaciones CU04 exigen tenant y no crean
    # nuevos perfiles sin esta columna.
    op.add_column(
        "medicos",
        sa.Column("id_clinica", sa.BigInteger(), sa.ForeignKey("clinicas.id_clinica"), nullable=True),
    )
    op.execute(
        """
        UPDATE medicos
        SET id_clinica = (
            SELECT usuarios.id_clinica
            FROM usuarios
            WHERE usuarios.id_usuario = medicos.id_usuario
        )
        WHERE id_clinica IS NULL
        """
    )
    op.create_index("ix_medicos_id_clinica", "medicos", ["id_clinica"], unique=False)
    op.drop_constraint("uq_medicos_matricula_profesional", "medicos", type_="unique")
    op.create_unique_constraint(
        "uq_medicos_clinica_matricula", "medicos", ["id_clinica", "matricula_profesional"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_medicos_clinica_matricula", "medicos", type_="unique")
    op.create_unique_constraint("uq_medicos_matricula_profesional", "medicos", ["matricula_profesional"])
    op.drop_index("ix_medicos_id_clinica", table_name="medicos")
    op.drop_column("medicos", "id_clinica")
