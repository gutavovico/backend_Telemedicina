"""Crear tabla tratamiento_operaciones_dosis para control concurrente y durable CU17.

Revision ID: 014_operaciones_dosis_cu17
Revises: cu17_tratamientos_013
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "014_operaciones_dosis_cu17"
down_revision = "cu17_tratamientos_013"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_VALUE = JSONB().with_variant(sa.JSON(), "sqlite")


def pk(name):
    return sa.Column(name, ID, primary_key=True, autoincrement=True)


def fk(name, target, nullable=False):
    return sa.Column(name, ID, sa.ForeignKey(target), nullable=nullable)


def timestamp(name, nullable=False, default=None):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=default)


def upgrade():
    op.create_table(
        "tratamiento_operaciones_dosis",
        pk("id_operacion"),
        fk("id_clinica", "clinicas.id_clinica"),
        fk("id_tratamiento", "tratamientos.id_tratamiento"),
        fk("id_dosis", "tratamiento_dosis.id_dosis"),
        fk("id_usuario", "usuarios.id_usuario"),
        sa.Column("generacion", ID, nullable=False, server_default="1"),
        sa.Column("idempotencia_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="EN_CURSO"),
        sa.Column("respuesta_json", JSON_VALUE, nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        timestamp("created_at", False, sa.func.now()),
        timestamp("updated_at", False, sa.func.now()),
        sa.UniqueConstraint(
            "id_clinica", "id_usuario", "id_dosis", "idempotencia_hash",
            name="uq_tratamiento_operacion_idempotencia"
        ),
        sa.CheckConstraint(
            "estado IN ('EN_CURSO','CONFIRMADA','RECHAZADA')",
            name="ck_tratamiento_operacion_estado"
        ),
    )
    op.create_index(
        "uq_op_dosis_activa",
        "tratamiento_operaciones_dosis",
        ["id_clinica", "id_dosis"],
        unique=True,
        postgresql_where=sa.text("estado = 'EN_CURSO'"),
        sqlite_where=sa.text("estado = 'EN_CURSO'"),
    )
    op.create_index(
        "ix_tratamiento_operacion_dosis",
        "tratamiento_operaciones_dosis",
        ["id_clinica", "id_dosis"],
    )

    op.add_column("tratamiento_dosis", sa.Column("generacion", ID, nullable=False, server_default="1"))

    # Migra/backfill de filas ya existentes en tratamiento_eventos donde
    # accion = 'REGISTRAR_DOSIS' y idempotencia_hash IS NOT NULL insertándolas
    # con estado = 'CONFIRMADA' para preservar 100% el historial existente de CU17.
    op.execute(
        sa.text(
            "INSERT INTO tratamiento_operaciones_dosis ("
            "  id_clinica, id_tratamiento, id_dosis, id_usuario, generacion, "
            "  idempotencia_hash, request_hash, estado, respuesta_json, created_at, updated_at"
            ") "
            "SELECT "
            "  id_clinica, id_tratamiento, id_dosis, id_usuario, 1, "
            "  idempotencia_hash, COALESCE(request_hash, ''), 'CONFIRMADA', respuesta_json, ocurrida_en_utc, ocurrida_en_utc "
            "FROM tratamiento_eventos "
            "WHERE accion = 'REGISTRAR_DOSIS' AND idempotencia_hash IS NOT NULL AND id_dosis IS NOT NULL"
        )
    )


def downgrade():
    raise RuntimeError(
        "CU17 conserva datos clínicos e historial de operaciones; la reversión operativa desactiva las rutas y el trabajo, sin borrar tablas ni operaciones"
    )
