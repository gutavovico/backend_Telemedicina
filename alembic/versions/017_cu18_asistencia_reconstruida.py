"""Recupera la revisión CU18 de asistencia inteligente aplicada en Neon.

Revision ID: cu18_asistencia_017
Revises: cu34_catalogo_016

Esta revisión se aplicó en la base de datos de despliegue, pero su archivo no
llegó a consolidarse en Git. Sin este nodo, Alembic no puede continuar desde
``cu18_asistencia_017`` porque la revisión no existe en el grafo local.

El DDL usa ``IF NOT EXISTS`` para que la reconstrucción sea segura tanto en
Neon (donde las tablas ya existen) como en una base PostgreSQL nueva.
"""
from alembic import op
import sqlalchemy as sa


revision = "cu18_asistencia_017"
down_revision = "cu34_catalogo_016"
branch_labels = None
depends_on = None


_AVISO_LEGAL = (
    "Esta asistencia inteligente apoya con alertas y sugerencias de autocuidado. "
    "No sustituye la valoración médica profesional ni modifica diagnósticos, "
    "dosis o prescripciones vigentes."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS evaluaciones_asistencia (
                id_evaluacion BIGSERIAL PRIMARY KEY,
                id_clinica BIGINT NOT NULL REFERENCES clinicas(id_clinica),
                id_paciente BIGINT NOT NULL REFERENCES pacientes(id_paciente),
                id_usuario BIGINT NOT NULL REFERENCES usuarios(id_usuario),
                fecha_evaluacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                estado_evaluacion VARCHAR(30) NOT NULL,
                nivel_riesgo_global VARCHAR(20) NOT NULL,
                total_medicamentos_analizados INTEGER NOT NULL DEFAULT 0,
                total_alertas_detectadas INTEGER NOT NULL DEFAULT 0,
                resumen_ejecutivo TEXT,
                aviso_legal TEXT NOT NULL,
                hash_prescripciones VARCHAR(64),
                proveedor_ia_utilizado VARCHAR(50),
                medicamentos_snapshot JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS interacciones_catalogo (
                id_interaccion BIGSERIAL PRIMARY KEY,
                principio_activo_a VARCHAR(200) NOT NULL,
                principio_activo_b VARCHAR(200) NOT NULL,
                severidad VARCHAR(20) NOT NULL
                    CHECK (severidad IN ('LEVE', 'MODERADA', 'GRAVE')),
                mecanismo TEXT,
                descripcion_riesgo TEXT NOT NULL,
                recomendacion_clinica TEXT NOT NULL,
                estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO'
                    CHECK (estado IN ('ACTIVO', 'INACTIVO')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_interacciones_catalogo_par
                    UNIQUE (principio_activo_a, principio_activo_b)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS alertas_interaccion (
                id_alerta BIGSERIAL PRIMARY KEY,
                id_evaluacion BIGINT NOT NULL
                    REFERENCES evaluaciones_asistencia(id_evaluacion) ON DELETE CASCADE,
                id_interaccion BIGINT REFERENCES interacciones_catalogo(id_interaccion),
                principio_activo_1 VARCHAR(200) NOT NULL,
                principio_activo_2 VARCHAR(200) NOT NULL,
                medicamento_1_nombre VARCHAR(200) NOT NULL,
                medicamento_2_nombre VARCHAR(200) NOT NULL,
                severidad VARCHAR(20) NOT NULL
                    CHECK (severidad IN ('LEVE', 'MODERADA', 'GRAVE')),
                color_alerta VARCHAR(20) NOT NULL,
                mensaje_alerta TEXT NOT NULL,
                pauta_precaucion TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )

    # Valores por defecto y restricciones que en la base desplegada ya existen.
    op.execute(
        sa.text(
            "ALTER TABLE evaluaciones_asistencia "
            "ALTER COLUMN aviso_legal SET DEFAULT :aviso_legal"
        ).bindparams(aviso_legal=_AVISO_LEGAL)
    )

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_evaluaciones_cache "
            "ON evaluaciones_asistencia "
            "(id_clinica, id_paciente, hash_prescripciones, fecha_evaluacion)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_evaluaciones_clinica_fecha "
            "ON evaluaciones_asistencia (id_clinica, fecha_evaluacion)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_evaluaciones_clinica_paciente "
            "ON evaluaciones_asistencia (id_clinica, id_paciente)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_interacciones_activo_a "
            "ON interacciones_catalogo (principio_activo_a)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_interacciones_activo_b "
            "ON interacciones_catalogo (principio_activo_b)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_alertas_evaluacion "
            "ON alertas_interaccion (id_evaluacion)"
        )
    )


def downgrade() -> None:
    # No se eliminan tablas automáticamente: pueden contener datos clínicos y
    # el rollback de una revisión recuperada requiere un plan explícito de
    # preservación de datos.
    pass
