"""Tablas y columnas de CU30, CU31, CU32 y servicios de CU06.

Revision ID: tenants_cu30_31_32_016
Revises: 1d58545ddd2c

Hasta esta revisión las tablas de gestión de tenants, suscripciones, pagos de
suscripción y solicitudes de baja sólo existían en los modelos SQLAlchemy; en
PostgreSQL/Neon no había DDL que las creara. También faltaban las columnas de
CU06 en `servicios_medicos` (modalidad, clínica y tenant) y el índice de
búsqueda. Todo es idempotente para convivir con bases donde ya se crearon por
`metadata.create_all`.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "tenants_cu30_31_32_016"
down_revision: Union[str, Sequence[str], None] = "1d58545ddd2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # CU30: columnas de ciclo de vida y acuerdo comercial del tenant.
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE clinicas ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)")
    op.execute("ALTER TABLE clinicas ADD COLUMN IF NOT EXISTS plan_id VARCHAR(36)")
    op.execute("ALTER TABLE clinicas ADD COLUMN IF NOT EXISTS commercial_notes TEXT")
    op.execute(
        "ALTER TABLE clinicas ADD COLUMN IF NOT EXISTS row_version "
        "INTEGER NOT NULL DEFAULT 1"
    )
    # Cada clínica existente recibe su discriminador antes de exponer CU30.
    op.execute("UPDATE clinicas SET tenant_id = gen_random_uuid()::text WHERE tenant_id IS NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_clinicas_tenant_id "
        "ON clinicas (tenant_id)"
    )

    # ------------------------------------------------------------------
    # CU30: solicitudes de alta (destino del portal público de CU32).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_requests (
            id_request VARCHAR(36) PRIMARY KEY,
            institucion_nombre VARCHAR(150) NOT NULL,
            razon_social VARCHAR(200),
            nit VARCHAR(50) NOT NULL,
            correo VARCHAR(150) NOT NULL,
            telefono VARCHAR(30),
            direccion VARCHAR(250),
            responsable_nombre VARCHAR(150) NOT NULL,
            responsable_correo VARCHAR(150) NOT NULL,
            responsable_telefono VARCHAR(30),
            plan_version_id VARCHAR(36),
            documentos_metadata TEXT,
            tracking_code VARCHAR(64) NOT NULL UNIQUE,
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            correlation_id VARCHAR(64),
            client_ip VARCHAR(45),
            user_agent VARCHAR(512),
            decision_motivo TEXT,
            decision_fecha TIMESTAMPTZ,
            tenant_id VARCHAR(36),
            id_clinica BIGINT,
            row_version INTEGER NOT NULL DEFAULT 1,
            fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Repara tablas creadas antes de esta revisión (p. ej. con
    # `metadata.create_all`): CREATE TABLE IF NOT EXISTS no agrega columnas.
    for column_ddl in (
        "razon_social VARCHAR(200)",
        "telefono VARCHAR(30)",
        "direccion VARCHAR(250)",
        "responsable_telefono VARCHAR(30)",
        "plan_version_id VARCHAR(36)",
        "documentos_metadata TEXT",
        "correlation_id VARCHAR(64)",
        "client_ip VARCHAR(45)",
        "user_agent VARCHAR(512)",
        "decision_motivo TEXT",
        "decision_fecha TIMESTAMPTZ",
        "tenant_id VARCHAR(36)",
        "id_clinica BIGINT",
        "row_version INTEGER NOT NULL DEFAULT 1",
        "fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP",
    ):
        op.execute(f"ALTER TABLE tenant_requests ADD COLUMN IF NOT EXISTS {column_ddl}")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_requests_nit ON tenant_requests (nit)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_requests_correlation "
        "ON tenant_requests (correlation_id)"
    )

    # ------------------------------------------------------------------
    # CU31: planes, suscripciones y pagos de suscripción.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_versions (
            id_plan_version VARCHAR(36) PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            descripcion TEXT,
            precio_mensual NUMERIC(10, 2) NOT NULL DEFAULT 0,
            precio_anual NUMERIC(10, 2) NOT NULL DEFAULT 0,
            moneda VARCHAR(10) NOT NULL DEFAULT 'BOB',
            limite_medicos INTEGER NOT NULL DEFAULT 10,
            limite_consultas_mes INTEGER NOT NULL DEFAULT 100,
            estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
            fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_subscriptions (
            id_suscripcion VARCHAR(36) PRIMARY KEY,
            id_clinica BIGINT NOT NULL UNIQUE REFERENCES clinicas(id_clinica),
            tenant_id VARCHAR(36),
            id_plan_version VARCHAR(36) NOT NULL
                REFERENCES plan_versions(id_plan_version),
            ciclo VARCHAR(20) NOT NULL DEFAULT 'MONTHLY',
            fecha_inicio TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_fin TIMESTAMPTZ NOT NULL,
            dias_gracia INTEGER NOT NULL DEFAULT 7,
            estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
            row_version INTEGER NOT NULL DEFAULT 1,
            fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_payments (
            id_pago_suscripcion VARCHAR(36) PRIMARY KEY,
            id_suscripcion VARCHAR(36) NOT NULL
                REFERENCES tenant_subscriptions(id_suscripcion),
            id_clinica BIGINT NOT NULL REFERENCES clinicas(id_clinica),
            tenant_id VARCHAR(36),
            id_usuario BIGINT NOT NULL REFERENCES usuarios(id_usuario),
            id_plan_version VARCHAR(36) NOT NULL
                REFERENCES plan_versions(id_plan_version),
            ciclo VARCHAR(20) NOT NULL,
            monto NUMERIC(10, 2) NOT NULL,
            moneda VARCHAR(10) NOT NULL DEFAULT 'BOB',
            estado VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            stripe_session_id VARCHAR(255) UNIQUE,
            stripe_payment_intent_id VARCHAR(255),
            url_checkout VARCHAR(1000),
            expira_en TIMESTAMPTZ,
            numero_factura VARCHAR(50) UNIQUE,
            fecha_pago TIMESTAMPTZ,
            fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_payments_suscripcion "
        "ON subscription_payments (id_suscripcion)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_payments_clinica "
        "ON subscription_payments (id_clinica)"
    )

    # ------------------------------------------------------------------
    # CU32: solicitudes de baja definitiva de un tenant activo.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_deactivation_requests (
            id_deactivation VARCHAR(36) PRIMARY KEY,
            id_clinica BIGINT NOT NULL REFERENCES clinicas(id_clinica),
            tenant_id VARCHAR(36),
            motivo TEXT NOT NULL,
            solicitante_id BIGINT NOT NULL REFERENCES usuarios(id_usuario),
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            decision_motivo TEXT,
            decision_fecha TIMESTAMPTZ,
            decidido_por BIGINT REFERENCES usuarios(id_usuario),
            row_version INTEGER NOT NULL DEFAULT 1,
            fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_deactivation_requests_clinica "
        "ON tenant_deactivation_requests (id_clinica)"
    )

    # ------------------------------------------------------------------
    # CU06: modalidad, costo y tenant de los servicios médicos.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE servicios_medicos ADD COLUMN IF NOT EXISTS id_clinica BIGINT "
        "REFERENCES clinicas(id_clinica) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE servicios_medicos ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)"
    )
    op.execute(
        "ALTER TABLE servicios_medicos ADD COLUMN IF NOT EXISTS modalidad "
        "VARCHAR(20) NOT NULL DEFAULT 'PRESENCIAL'"
    )
    # Backfill sólo cuando el servicio pertenece a una única clínica; los
    # servicios compartidos o sin horarios quedan sin dueño y CU06 no los ofrece.
    op.execute(
        """
        UPDATE servicios_medicos s
        SET id_clinica = dueno.id_clinica,
            tenant_id = c.tenant_id
        FROM (
            SELECT h.id_servicio, MIN(m.id_clinica) AS id_clinica
            FROM horarios_medicos h
            JOIN medicos m ON m.id_medico = h.id_medico
            WHERE m.id_clinica IS NOT NULL
            GROUP BY h.id_servicio
            HAVING COUNT(DISTINCT m.id_clinica) = 1
        ) AS dueno
        JOIN clinicas c ON c.id_clinica = dueno.id_clinica
        WHERE s.id_servicio = dueno.id_servicio
          AND s.id_clinica IS NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_servicios_medicos_clinica "
        "ON servicios_medicos (id_clinica)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_servicios_medicos_tenant_modalidad_costo "
        "ON servicios_medicos (tenant_id, modalidad, costo)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_servicios_medicos_tenant_modalidad_costo")
    op.execute("DROP INDEX IF EXISTS idx_servicios_medicos_clinica")
    op.execute("ALTER TABLE servicios_medicos DROP COLUMN IF EXISTS modalidad")
    op.execute("ALTER TABLE servicios_medicos DROP COLUMN IF EXISTS tenant_id")
    op.execute("ALTER TABLE servicios_medicos DROP COLUMN IF EXISTS id_clinica")

    op.execute("DROP TABLE IF EXISTS tenant_deactivation_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS subscription_payments CASCADE")
    op.execute("DROP TABLE IF EXISTS tenant_subscriptions CASCADE")
    op.execute("DROP TABLE IF EXISTS plan_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS tenant_requests CASCADE")

    op.execute("DROP INDEX IF EXISTS uq_clinicas_tenant_id")
    op.execute("ALTER TABLE clinicas DROP COLUMN IF EXISTS row_version")
    op.execute("ALTER TABLE clinicas DROP COLUMN IF EXISTS commercial_notes")
    op.execute("ALTER TABLE clinicas DROP COLUMN IF EXISTS plan_id")
    op.execute("ALTER TABLE clinicas DROP COLUMN IF EXISTS tenant_id")
