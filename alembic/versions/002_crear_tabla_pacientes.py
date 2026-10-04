"""crear_tabla_pacientes

Revision ID: 002_crear_tabla_pacientes
Revises: 001_crear_tabla_usuarios
Create Date: 2026-08-24 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_crear_tabla_pacientes'
down_revision: Union[str, None] = '001_crear_tabla_usuarios'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pacientes',
        sa.Column('id_paciente', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('id_usuario', sa.BigInteger(), nullable=True),
        sa.Column('nombres', sa.String(length=100), nullable=False),
        sa.Column('apellidos', sa.String(length=100), nullable=False),
        sa.Column('ci', sa.String(length=20), nullable=False),
        sa.Column('complemento', sa.String(length=10), nullable=True, server_default=''),
        sa.Column('fecha_nacimiento', sa.Date(), nullable=False),
        sa.Column('genero', sa.String(length=10), nullable=False),
        sa.Column('telefono', sa.String(length=20), nullable=False),
        sa.Column('correo', sa.String(length=150), nullable=True),
        sa.Column('direccion', sa.String(length=255), nullable=True),
        sa.Column('ciudad', sa.String(length=100), nullable=True, server_default='Santa Cruz de la Sierra'),
        sa.Column('tipo_sangre', sa.String(length=5), nullable=True),
        sa.Column('alergias', sa.Text(), nullable=True),
        sa.Column('antecedentes_patologicos', sa.Text(), nullable=True),
        sa.Column('contacto_emergencia_nombre', sa.String(length=150), nullable=True),
        sa.Column('contacto_emergencia_telefono', sa.String(length=20), nullable=True),
        sa.Column('contacto_emergencia_parentesco', sa.String(length=50), nullable=True),
        sa.Column('seguro_medico', sa.String(length=100), nullable=True),
        sa.Column('numero_seguro', sa.String(length=50), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='ACTIVO'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id_paciente'),
        sa.ForeignKeyConstraint(['id_usuario'], ['usuarios.id_usuario'], ondelete='SET NULL'),
        sa.UniqueConstraint('ci', 'complemento', name='uq_pacientes_ci_complemento')
    )
    op.create_index(op.f('ix_pacientes_id_paciente'), 'pacientes', ['id_paciente'], unique=False)
    op.create_index(op.f('ix_pacientes_id_usuario'), 'pacientes', ['id_usuario'], unique=True)
    op.create_index(op.f('ix_pacientes_ci'), 'pacientes', ['ci'], unique=False)
    op.create_index(op.f('ix_pacientes_estado'), 'pacientes', ['estado'], unique=False)
    op.create_index('idx_pacientes_nombres_apellidos', 'pacientes', ['nombres', 'apellidos'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_pacientes_nombres_apellidos', table_name='pacientes')
    op.drop_index(op.f('ix_pacientes_estado'), table_name='pacientes')
    op.drop_index(op.f('ix_pacientes_ci'), table_name='pacientes')
    op.drop_index(op.f('ix_pacientes_id_usuario'), table_name='pacientes')
    op.drop_index(op.f('ix_pacientes_id_paciente'), table_name='pacientes')
    op.drop_table('pacientes')
