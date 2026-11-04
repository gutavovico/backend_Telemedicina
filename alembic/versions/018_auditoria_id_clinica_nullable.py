"""Permite auditoría global (id_clinica NULL) del Superadministrador.

Revision ID: audit_tenant_nullable_018
Revises: cu32_repair_017

El modelo ORM declara `Auditoria.id_clinica` como nullable porque las acciones
de plataforma (aprobar/rechazar altas, suspender tenants, accesos denegados) no
pertenecen a ningún tenant. Las revisiones 007 y 012 crearon la columna como
`NOT NULL`, así que insertar la traza fallaba con NotNullViolation y rompía la
aprobación de una solicitud de alta con 500.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "audit_tenant_nullable_018"
down_revision: Union[str, Sequence[str], None] = "cu32_repair_017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE auditoria ALTER COLUMN id_clinica DROP NOT NULL")


def downgrade() -> None:
    # Falla a propósito si existen trazas globales (id_clinica IS NULL):
    # borrar auditoría para poder revertir no es aceptable.
    op.execute("ALTER TABLE auditoria ALTER COLUMN id_clinica SET NOT NULL")
