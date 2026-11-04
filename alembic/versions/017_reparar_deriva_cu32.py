"""Repara la deriva de las tablas de CU30/CU32 creadas antes de la revisión 016.

Revision ID: cu32_repair_017
Revises: tenants_cu30_31_32_016

`CREATE TABLE IF NOT EXISTS` de la revisión 016 no agrega columnas cuando la
tabla ya existía (por ejemplo, creada con `metadata.create_all`). Esta
revisión completa las columnas que el modelo SQLAlchemy ya declara.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "cu32_repair_017"
down_revision: Union[str, Sequence[str], None] = "tenants_cu30_31_32_016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column_ddl in (
        "razon_social VARCHAR(200)",
        "telefono VARCHAR(30)",
        "direccion VARCHAR(250)",
        "responsable_telefono VARCHAR(30)",
        "plan_version_id VARCHAR(36)",
        "documentos_metadata TEXT",
        "correlation_id VARCHAR(64)",
        "client_ip VARCHAR(45)",
        "user_agent VARCHAR(512)",
        "decision_motivo TEXT",
        "decision_fecha TIMESTAMPTZ",
        "tenant_id VARCHAR(36)",
        "id_clinica BIGINT",
        "row_version INTEGER NOT NULL DEFAULT 1",
        "fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP",
    ):
        op.execute(f"ALTER TABLE tenant_requests ADD COLUMN IF NOT EXISTS {column_ddl}")

    for column_ddl in (
        "tenant_id VARCHAR(36)",
        "decision_motivo TEXT",
        "decision_fecha TIMESTAMPTZ",
        "decidido_por BIGINT REFERENCES usuarios(id_usuario)",
        "row_version INTEGER NOT NULL DEFAULT 1",
        "fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP",
    ):
        op.execute(
            "ALTER TABLE tenant_deactivation_requests "
            f"ADD COLUMN IF NOT EXISTS {column_ddl}"
        )


def downgrade() -> None:
    for column in (
        "decidido_por",
        "decision_fecha",
        "decision_motivo",
        "tenant_id",
    ):
        op.execute(
            f"ALTER TABLE tenant_deactivation_requests DROP COLUMN IF EXISTS {column}"
        )
