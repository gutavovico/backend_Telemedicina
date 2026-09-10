"""tablas_auditoria_cu21

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-10 04:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if 'auditoria' not in tables:
        op.create_table(
            'auditoria',
            sa.Column('id_auditoria', sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column('id_clinica', sa.BigInteger(), nullable=False),
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
        op.create_index('ix_auditoria_id_clinica', 'auditoria', ['id_clinica'], unique=False)
        op.create_index('ix_auditoria_id_usuario', 'auditoria', ['id_usuario'], unique=False)
        op.create_index('ix_auditoria_fecha_hora', 'auditoria', ['fecha_hora'], unique=False)
        op.create_index('ix_auditoria_accion', 'auditoria', ['accion'], unique=False)
    else:
        # Si la tabla ya existía, asegurarse de los índices de consulta para CU21
        indexes = [idx['name'] for idx in inspector.get_indexes('auditoria')]
        if 'ix_auditoria_id_clinica' not in indexes:
            try:
                op.create_index('ix_auditoria_id_clinica', 'auditoria', ['id_clinica'], unique=False)
            except Exception:
                pass
        if 'ix_auditoria_fecha_hora' not in indexes:
            try:
                op.create_index('ix_auditoria_fecha_hora', 'auditoria', ['fecha_hora'], unique=False)
            except Exception:
                pass


def downgrade() -> None:
    try:
        op.drop_index('ix_auditoria_fecha_hora', table_name='auditoria')
        op.drop_index('ix_auditoria_id_clinica', table_name='auditoria')
        op.drop_index('ix_auditoria_id_auditoria', table_name='auditoria')
        op.drop_table('auditoria')
    except Exception:
        pass
