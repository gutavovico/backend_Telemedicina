"""Rol global Super Administrador SaaS (id_clinica=None).

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Upsert idempotente: solo si no existe un rol global con ese nombre.
    conn.execute(
        sa.text(
            """
            INSERT INTO roles (id_clinica, nombre, descripcion, estado)
            SELECT NULL, 'Super Administrador',
                   'Acceso total y administración de la plataforma SaaS',
                   'ACTIVO'
            WHERE NOT EXISTS (
                SELECT 1 FROM roles
                WHERE id_clinica IS NULL
                  AND lower(nombre) = lower('Super Administrador')
            )
            """
        )
    )


def downgrade() -> None:
    # No se elimina el rol en downgrade para no dejar huérfanos a los
    # superadmins existentes; solo se revierte el esquema si hiciera falta.
    pass
