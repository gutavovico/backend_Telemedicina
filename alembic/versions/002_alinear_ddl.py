"""002_alinear_ddl

Revision ID: 
Revises: 001_crear_tabla_usuarios
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '002_alinear_ddl'
down_revision: Union[str, None] = '001_crear_tabla_usuarios'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def tables_exist(connection, table_names):
    """Check if tables exist in the database."""
    inspector = inspect(connection)
    existing_tables = inspector.get_table_names()
    return all(t in existing_tables for t in table_names)


def columns_exist(connection, table_name, column_names):
    """Check if columns exist in a table."""
    inspector = inspect(connection)
    existing_columns = [c['name'] for c in inspector.get_columns(table_name)]
    return all(c in existing_columns for c in column_names)


def upgrade() -> None:
    bind = op.get_bind()
    
    # Tablas que deben existir (crear solo si no existen)
    tables_to_create = [
        (
            'clinicas',
            sa.Column('id_clinica', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('nombre', sa.String(length=150), nullable=False),
            sa.Column('razon_social', sa.String(length=200), nullable=True),
            sa.Column('nit', sa.String(length=50), unique=True, nullable=True),
            sa.Column('telefono', sa.String(length=30), nullable=True),
            sa.Column('correo', sa.String(length=150), nullable=True),
            sa.Column('direccion', sa.String(length=250), nullable=True),
            sa.Column('logo', sa.String(length=500), nullable=True),
            sa.Column('estado', sa.String(length=20), nullable=False, server_default='ACTIVO'),
            sa.Column('fecha_creacion', sa.DateTime(timezone=True), server_default=func.now(), nullable=False),
        ),
        (
            'roles',
            sa.Column('id_rol', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('id_clinica', sa.BigInteger(), ForeignKey('clinicas.id_clinica'), nullable=True),
            sa.Column('nombre', sa.String(length=100), nullable=False),
            sa.Column('descripcion', sa.String, nullable=True),
            sa.Column('estado', sa.String(length=20), nullable=False, server_default='ACTIVO'),
        ),
        (
            'notificaciones',
            sa.Column('id_notificacion', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('id_usuario', sa.BigInteger(), ForeignKey('usuarios.id_usuario'), nullable=False),
            sa.Column('tipo', sa.String(length=50), nullable=True),
            sa.Column('canal', sa.String(length=30), nullable=True),
            sa.Column('titulo', sa.String(length=200), nullable=True),
            sa.Column('mensaje', sa.Text, nullable=True),
            sa.Column('fecha_programada', sa.DateTime(timezone=True), nullable=True),
            sa.Column('fecha_envio', sa.DateTime(timezone=True), nullable=True),
            sa.Column('fecha_lectura', sa.DateTime(timezone=True), nullable=True),
            sa.Column('estado', sa.String(length=30), nullable=False, server_default='PENDIENTE'),
        ),
        (
            'auditoria',
            sa.Column('id_auditoria', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('id_clinica', sa.BigInteger(), ForeignKey('clinicas.id_clinica'), nullable=False),
            sa.Column('id_usuario', sa.BigInteger(), ForeignKey('usuarios.id_usuario'), nullable=False),
            sa.Column('tabla_afectada', sa.String(length=150), nullable=True),
            sa.Column('registro_id', sa.BigInteger(), nullable=True),
            sa.Column('accion', sa.String(length=50), nullable=False),
            sa.Column('descripcion', sa.Text, nullable=True),
            sa.Column('datos_anteriores', sa.Text, nullable=True),
            sa.Column('datos_nuevos', sa.Text, nullable=True),
            sa.Column('direccion_ip', sa.String(length=45), nullable=True),
            sa.Column('fecha_hora', sa.DateTime(timezone=True), server_default=func.now(), nullable=False),
        ),
    ]
    
    for table_def in tables_to_create:
        # Usar el nombre de la tabla como clave
        table_name = table_def.pop(0)  # First element es el nombre
        # Reestructurar: el primero es el nombre, el resto son columnas
        # Vamos a reescribir esto de forma más sencilla
        pass
    
    # En lugar de eso, usaremos un enfoque más simple:
    # Crear tablas solo si no existen usando IF NOT EXISTS
    # y agregar columnas a usuarios si faltan
    
    # Agregar columnas id_clinica e id_rol a usuarios si no existen
    with op.get_bind() as conn:
        insp = inspect(conn)
        existing_cols = [c['name'] for c in insp.get_columns('usuarios')]
        if 'id_clinica' not in existing_cols:
            op.add_column('usuarios', sa.Column('id_clinica', sa.BigInteger(), sa.ForeignKey('clinicas.id_clinica'), nullable=False))
        if 'id_rol' not in existing_cols:
            op.add_column('usuarios', sa.Column('id_rol', sa.BigInteger(), sa.ForeignKey('roles.id_rol'), nullable=False))
    
    # Crear tablas solo si no existen (usando SQL raw con IF NOT EXISTS)
    # Clinicas
    op.execute("""
        CREATE TABLE IF NOT EXISTS clinicas (
            id_clinica BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            nombre VARCHAR(150) NOT NULL,
            razon_social VARCHAR(200),
            nit VARCHAR(50) UNIQUE,
            telefono VARCHAR(30),
            correo VARCHAR(150),
            direccion VARCHAR(250),
            logo VARCHAR(500),
            estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVA',
            fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Roles
    op.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id_rol BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            id_clinica BIGINT REFERENCES clinicas(id_clinica),
            nombre VARCHAR(100) NOT NULL,
            descripcion TEXT,
            estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO')
        """)
    # Notificaciones
    op.execute("""
        CREATE TABLE IF NOT EXISTS notificaciones (
            id_notificacion BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            id_usuario BIGINT NOT NULL REFERENCES usuarios(id_usuario),
            tipo VARCHAR(50),
            canal VARCHAR(30),
            titulo VARCHAR(200),
            mensaje TEXT,
            fecha_programada TIMESTAMP,
            fecha_envio TIMESTAMP,
            fecha_lectura TIMESTAMP,
            estado VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE')
        """)
    # Auditoría
    op.execute("""
        CREATE TABLE IF NOT EXISTS auditoria (
            id_auditoria BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            id_clinica BIGINT NOT NULL REFERENCES clinicas(id_clinica),
            id_usuario BIGINT NOT NULL REFERENCES usuarios(id_usuario),
            tabla_afectada VARCHAR(150),
            registro_id BIGINT,
            accion VARCHAR(50) NOT NULL,
            descripcion TEXT,
            datos_anteriores JSONB,
            datos_nuevos JSONB,
            direccion_ip VARCHAR(45),
            fecha_hora TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)
        """)
    
    # Ahora agregar las restricciones y índices que faltan
    # Agregar restricción única en nit de clinicas si no existe
    op.execute("""
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'clinicas_nit_key') THEN
                CREATE UNIQUE INDEX clinitas_nit_key ON clinicas (nit);
            END IF;
        END\$\$;
    """)
    
    # Agregar restricción única en numero_historia de historias_clinicas
    op.execute("""
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'historias_clinicas_numero_historia_key') THEN
                CREATE UNIQUE INDEX historias_clinicas_numero_historia_key ON historias_clinicas (numero_historia);
            END IF;
        END\$\$;
    """)
    

def downgrade() -> None:
    # Lógica reversa: eliminar las columnas agregadas y dropar tablas
    with op.get_bind() as conn:
        insp = inspect(conn)
        # Verificar si las columnas existen antes de eliminarlas
        existing_cols = [c['name'] for c in insp.get_columns('usuarios')]
        if 'id_clinica' in existing_cols:
            op.drop_column('usuarios', 'id_clinica')
        if 'id_rol' in existing_cols:
            op.drop_column('usuarios', 'id_rol')
    
    # Dropar tablas solo si existen
    op.execute("DROP TABLE IF EXISTS auditoria")
    op.execute("DROP TABLE IF EXISTS notificaciones")
    op.execute("DROP TABLE IF EXISTS roles")
    op.execute("DROP TABLE IF EXISTS clinicas")
    
    # Restablecer restricciones únicas
    op.execute("""
        DROP INDEX IF EXISTS clinitas_nit_key;
        DROP INDEX IF EXISTS historias_clinicas_numero_historia_key;
    """)