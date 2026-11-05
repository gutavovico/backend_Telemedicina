"""Añade credenciales temporales seguras al onboarding institucional.

Revision ID: temp_credentials_019
Revises: audit_tenant_nullable_018
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "temp_credentials_019"
down_revision: Union[str, Sequence[str], None] = "audit_tenant_nullable_018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_requests",
        sa.Column("temporary_password_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "tenant_requests",
        sa.Column("temporary_password_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_requests",
        sa.Column(
            "temporary_password_reveal_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "tenant_requests",
        sa.Column("temporary_password_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_requests",
        sa.Column("temporary_password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_requests",
        sa.Column(
            "credentials_issued",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "tenant_request_tracking_audits",
        sa.Column(
            "id_audit",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id_request", sa.String(length=36), nullable=True),
        sa.Column("tracking_code_hash", sa.String(length=64), nullable=False),
        sa.Column("accion", sa.String(length=50), nullable=False),
        sa.Column("resultado", sa.String(length=30), nullable=False),
        sa.Column("direccion_ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "fecha_hora",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id_audit"),
    )
    op.create_index(
        "ix_tenant_request_tracking_audits_id_audit",
        "tenant_request_tracking_audits",
        ["id_audit"],
    )
    op.create_index(
        "ix_tenant_request_tracking_audits_id_request",
        "tenant_request_tracking_audits",
        ["id_request"],
    )
    op.create_index(
        "ix_tenant_request_tracking_audits_tracking_code_hash",
        "tenant_request_tracking_audits",
        ["tracking_code_hash"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_request_tracking_audits_tracking_code_hash",
        table_name="tenant_request_tracking_audits",
    )
    op.drop_index(
        "ix_tenant_request_tracking_audits_id_request",
        table_name="tenant_request_tracking_audits",
    )
    op.drop_index(
        "ix_tenant_request_tracking_audits_id_audit",
        table_name="tenant_request_tracking_audits",
    )
    op.drop_table("tenant_request_tracking_audits")
    op.drop_column("tenant_requests", "credentials_issued")
    op.drop_column("tenant_requests", "temporary_password_used_at")
    op.drop_column("tenant_requests", "temporary_password_changed_at")
    op.drop_column("tenant_requests", "temporary_password_reveal_count")
    op.drop_column("tenant_requests", "temporary_password_expires_at")
    op.drop_column("tenant_requests", "temporary_password_encrypted")
