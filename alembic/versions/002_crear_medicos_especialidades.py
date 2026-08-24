"""crear_tablas_medicos_especialidades (CU04)

Revision ID: 002_crear_medicos_especialidades
Revises: 001_crear_tabla_usuarios
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_crear_medicos_especialidades'
down_revision: Union[str, None] = '001_crear_tabla_usuarios'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Catálogo de especialidades
    op.create_table(
        'especialidades',
        sa.Column('id_especialidad', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='activo'),
        sa.PrimaryKeyConstraint('id_especialidad'),
        sa.UniqueConstraint('nombre', name='uq_especialidades_nombre'),
    )
    op.create_index(op.f('ix_especialidades_id_especialidad'), 'especialidades', ['id_especialidad'], unique=False)

    # Perfil profesional de médicos (1:1 con usuarios)
    op.create_table(
        'medicos',
        sa.Column('id_medico', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('id_usuario', sa.BigInteger(), nullable=False),
        sa.Column('matricula_profesional', sa.String(length=30), nullable=False),
        sa.Column('descripcion_profesional', sa.Text(), nullable=True),
        sa.Column('experiencia', sa.Text(), nullable=True),
        sa.Column('foto_perfil', sa.String(length=500), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='activo'),
        sa.Column('fecha_registro', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id_medico'),
        sa.ForeignKeyConstraint(['id_usuario'], ['usuarios.id_usuario'], ondelete='CASCADE'),
        sa.UniqueConstraint('id_usuario', name='uq_medicos_id_usuario'),
        sa.UniqueConstraint('matricula_profesional', name='uq_medicos_matricula_profesional'),
    )
    op.create_index(op.f('ix_medicos_id_medico'), 'medicos', ['id_medico'], unique=False)
    op.create_index(op.f('ix_medicos_matricula_profesional'), 'medicos', ['matricula_profesional'], unique=False)
    op.create_index(op.f('ix_medicos_id_usuario'), 'medicos', ['id_usuario'], unique=False)

    # Asociación N:M médico <-> especialidad
    op.create_table(
        'medico_especialidad',
        sa.Column('id_medico', sa.BigInteger(), nullable=False),
        sa.Column('id_especialidad', sa.BigInteger(), nullable=False),
        sa.Column('es_principal', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.PrimaryKeyConstraint('id_medico', 'id_especialidad'),
        sa.ForeignKeyConstraint(['id_medico'], ['medicos.id_medico'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['id_especialidad'], ['especialidades.id_especialidad'], ondelete='CASCADE'),
        sa.UniqueConstraint('id_medico', 'id_especialidad', name='uq_medico_especialidad'),
    )


def downgrade() -> None:
    op.drop_table('medico_especialidad')
    op.drop_index(op.f('ix_medicos_id_usuario'), table_name='medicos')
    op.drop_index(op.f('ix_medicos_matricula_profesional'), table_name='medicos')
    op.drop_index(op.f('ix_medicos_id_medico'), table_name='medicos')
    op.drop_table('medicos')
    op.drop_index(op.f('ix_especialidades_id_especialidad'), table_name='especialidades')
    op.drop_table('especialidades')
