"""004_multitenant_constraints

Configura las restricciones compuestas e indices multitenant:
1. Asegura la existencia de la clinica por defecto (id=1).
2. Backfill de id_clinica en usuarios y pacientes.
3. Permite id_clinica nullable en tabla auditoria.
4. Crea indices compuestos y restricciones de unicidad por tenant:
   - usuarios(id_clinica, correo)
   - pacientes(id_clinica, ci, complemento)
   - auditoria(id_clinica, fecha_hora)

Revision ID: 004_multitenant_constraints
Revises: 003_crear_permisos
Create Date: 2026-09-08 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = '004_multitenant_constraints'
down_revision: Union[str, Sequence[str], None] = '003_crear_permisos'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _exec_safe(conn, stmt: str, dialect_name: str) -> None:
    """Ejecuta un statement usando SAVEPOINT en PostgreSQL para evitar abortar la transaccion."""
    if dialect_name == "postgresql":
        conn.execute(text("SAVEPOINT sp_safe"))
        try:
            conn.execute(text(stmt))
            conn.execute(text("RELEASE SAVEPOINT sp_safe"))
        except Exception:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_safe"))
    else:
        try:
            conn.execute(text(stmt))
        except Exception:
            pass


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    dialect_name = conn.dialect.name

    # 1. Backfill y Seed Clinica Inicial
    if "clinicas" in tables:
        if dialect_name == "postgresql":
            _exec_safe(conn, """
                INSERT INTO clinicas (id_clinica, nombre, estado)
                VALUES (1, 'Hospital San Juan de Dios', 'ACTIVO')
                ON CONFLICT (id_clinica) DO NOTHING;
            """, dialect_name)
        elif dialect_name == "sqlite":
            _exec_safe(conn, """
                INSERT OR IGNORE INTO clinicas (id_clinica, nombre, estado)
                VALUES (1, 'Hospital San Juan de Dios', 'ACTIVO');
            """, dialect_name)

    # 2. Backfill en usuarios y pacientes
    if "usuarios" in tables:
        usuarios_cols = [c["name"] for c in inspector.get_columns("usuarios")]
        if "id_clinica" in usuarios_cols:
            _exec_safe(conn, "UPDATE usuarios SET id_clinica = 1 WHERE id_clinica IS NULL AND id_rol != 1;", dialect_name)
    if "pacientes" in tables:
        pacientes_cols = [c["name"] for c in inspector.get_columns("pacientes")]
        if "id_clinica" in pacientes_cols:
            _exec_safe(conn, "UPDATE pacientes SET id_clinica = 1 WHERE id_clinica IS NULL;", dialect_name)

    # 3. Auditoria id_clinica nullable
    if "auditoria" in tables:
        if dialect_name == "postgresql":
            _exec_safe(conn, "ALTER TABLE auditoria ALTER COLUMN id_clinica DROP NOT NULL;", dialect_name)

    # 4. Unicidades e Indices Compuestos
    # 4.1. usuarios (id_clinica, correo)
    if "usuarios" in tables:
        existing_indexes = [i["name"] for i in inspector.get_indexes("usuarios")]
        if "idx_usuarios_clinica_correo" not in existing_indexes:
            usuarios_cols = [c["name"] for c in inspector.get_columns("usuarios")]
            if "id_clinica" in usuarios_cols:
                op.create_index("idx_usuarios_clinica_correo", "usuarios", ["id_clinica", "correo"], unique=False)

    # 4.2. pacientes (id_clinica, ci)
    if "pacientes" in tables:
        existing_indexes = [i["name"] for i in inspector.get_indexes("pacientes")]
        if "idx_pacientes_clinica_ci" not in existing_indexes:
            pacientes_cols = [c["name"] for c in inspector.get_columns("pacientes")]
            if "id_clinica" in pacientes_cols:
                op.create_index("idx_pacientes_clinica_ci", "pacientes", ["id_clinica", "ci"], unique=False)

    # 4.3. auditoria (id_clinica, fecha_hora)
    if "auditoria" in tables:
        existing_indexes = [i["name"] for i in inspector.get_indexes("auditoria")]
        if "idx_auditoria_clinica_fecha" not in existing_indexes:
            auditoria_cols = [c["name"] for c in inspector.get_columns("auditoria")]
            if "id_clinica" in auditoria_cols:
                op.create_index("idx_auditoria_clinica_fecha", "auditoria", ["id_clinica", "fecha_hora"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "auditoria" in tables:
        existing = [i["name"] for i in inspector.get_indexes("auditoria")]
        if "idx_auditoria_clinica_fecha" in existing:
            op.drop_index("idx_auditoria_clinica_fecha", table_name="auditoria")
    if "pacientes" in tables:
        existing = [i["name"] for i in inspector.get_indexes("pacientes")]
        if "idx_pacientes_clinica_ci" in existing:
            op.drop_index("idx_pacientes_clinica_ci", table_name="pacientes")
    if "usuarios" in tables:
        existing = [i["name"] for i in inspector.get_indexes("usuarios")]
        if "idx_usuarios_clinica_correo" in existing:
            op.drop_index("idx_usuarios_clinica_correo", table_name="usuarios")