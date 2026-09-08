"""crear_token_blacklist_auditoria y merge heads

Revision ID: 005_token_blacklist
Revises: e9b1a6ac1592, 004_multitenant_constraints
Create Date: 2026-09-07 21:18:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = '005_token_blacklist'
down_revision: Union[str, Sequence[str], None] = ('e9b1a6ac1592', '004_multitenant_constraints')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if 'token_blacklist' not in tables:
        op.create_table(
            'token_blacklist',
            sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column('token', sa.String(length=500), nullable=False),
            sa.Column('revoked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('token'),
        )
        op.create_index('ix_token_blacklist_id', 'token_blacklist', ['id'], unique=False)
        op.create_index('ix_token_blacklist_token', 'token_blacklist', ['token'], unique=True)

    if 'auditoria' not in tables:
        op.create_table(
            'auditoria',
            sa.Column('id_auditoria', sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column('id_clinica', sa.BigInteger(), nullable=True),
            sa.Column('id_usuario', sa.BigInteger(), nullable=False),
            sa.Column('tabla_afectada', sa.String(length=150), nullable=True),
            sa.Column('registro_id', sa.BigInteger(), nullable=True),
            sa.Column('accion', sa.String(length=50), nullable=False),
            sa.Column('descripcion', sa.String(), nullable=True),
            sa.Column('datos_anteriores', sa.String(), nullable=True),
            sa.Column('datos_nuevos', sa.String(), nullable=True),
            sa.Column('direccion_ip', sa.String(length=45), nullable=True),
            sa.Column('fecha_hora', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['id_clinica'], ['clinicas.id_clinica']),
            sa.ForeignKeyConstraint(['id_usuario'], ['usuarios.id_usuario']),
            sa.PrimaryKeyConstraint('id_auditoria'),
        )
        op.create_index('ix_auditoria_id_auditoria', 'auditoria', ['id_auditoria'], unique=False)


def downgrade() -> None:
    try:
        op.drop_index('ix_auditoria_id_auditoria', table_name='auditoria')
        op.drop_table('auditoria')
    except Exception:
        pass
    try:
        op.drop_index('ix_token_blacklist_token', table_name='token_blacklist')
        op.drop_index('ix_token_blacklist_id', table_name='token_blacklist')
        op.drop_table('token_blacklist')
    except Exception:
        pass