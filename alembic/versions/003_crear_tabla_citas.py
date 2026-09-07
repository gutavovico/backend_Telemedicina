"""003_crear_tabla_citas

Revision ID: 003_crear_tabla_citas
Revises: e9b1a6ac1592
Create Date: 2026-09-06 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_crear_tabla_citas'
down_revision: Union[str, Sequence[str], None] = 'e9b1a6ac1592'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'citas',
        sa.Column('id_cita', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('id_paciente', sa.BigInteger(), nullable=False),
        sa.Column('id_medico', sa.BigInteger(), nullable=False),
        sa.Column('id_especialidad', sa.BigInteger(), nullable=True),
        sa.Column('fecha_cita', sa.Date(), nullable=False),
        sa.Column('hora_inicio', sa.String(length=10), nullable=False),
        sa.Column('hora_fin', sa.String(length=10), nullable=True),
        sa.Column('motivo', sa.Text(), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='PENDIENTE'),
        sa.Column('tipo_consulta', sa.String(length=20), nullable=False, server_default='TELEMEDICINA'),
        sa.Column('notas', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['id_paciente'], ['pacientes.id_paciente'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['id_medico'], ['medicos.id_medico'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['id_especialidad'], ['especialidades.id_especialidad'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id_cita')
    )
    op.create_index(op.f('ix_citas_id_cita'), 'citas', ['id_cita'], unique=False)
    op.create_index(op.f('ix_citas_id_paciente'), 'citas', ['id_paciente'], unique=False)
    op.create_index(op.f('ix_citas_id_medico'), 'citas', ['id_medico'], unique=False)
    op.create_index(op.f('ix_citas_fecha_cita'), 'citas', ['fecha_cita'], unique=False)
    op.create_index(op.f('ix_citas_estado'), 'citas', ['estado'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_citas_estado'), table_name='citas')
    op.drop_index(op.f('ix_citas_fecha_cita'), table_name='citas')
    op.drop_index(op.f('ix_citas_id_medico'), table_name='citas')
    op.drop_index(op.f('ix_citas_id_paciente'), table_name='citas')
    op.drop_index(op.f('ix_citas_id_cita'), table_name='citas')
    op.drop_table('citas')

