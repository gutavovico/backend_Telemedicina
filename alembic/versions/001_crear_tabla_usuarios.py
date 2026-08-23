"""crear_tabla_usuarios

Revision ID: 001_crear_tabla_usuarios
Revises: 
Create Date: 2026-08-22 20:42:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_crear_tabla_usuarios'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usuarios',
        sa.Column('id_usuario', sa.BigInteger(), autoincrement=True, nullable=False),
        # sa.Column('id_clinica', sa.BigInteger(), nullable=True),  # Pendiente
        # sa.Column('id_rol', sa.BigInteger(), nullable=True),      # Pendiente
        sa.Column('nombres', sa.String(length=100), nullable=False),
        sa.Column('apellidos', sa.String(length=100), nullable=False),
        sa.Column('correo', sa.String(length=150), nullable=False),
        sa.Column('telefono', sa.String(length=20), nullable=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('foto_perfil', sa.String(length=500), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='activo'),
        sa.Column('notificaciones_push', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('notificaciones_email', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('notificaciones_sms', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('fecha_creacion', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('fecha_actualizacion', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id_usuario')
    )
    op.create_index(op.f('ix_usuarios_correo'), 'usuarios', ['correo'], unique=True)
    op.create_index(op.f('ix_usuarios_id_usuario'), 'usuarios', ['id_usuario'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_usuarios_id_usuario'), table_name='usuarios')
    op.drop_index(op.f('ix_usuarios_correo'), table_name='usuarios')
    op.drop_table('usuarios')
