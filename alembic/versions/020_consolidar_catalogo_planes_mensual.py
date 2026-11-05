"""Consolida el catálogo CU34 y restringe suscripciones al ciclo mensual.

La migración conserva ``plan_versions`` y crea un mapeo UUID -> BIGINT para
trazabilidad y rollback seguro.
"""
from alembic import op
import sqlalchemy as sa


revision = "cu34_consolidacion_020"
down_revision = "62b0d532ee0a"
branch_labels = None
depends_on = None


_CANONICAL_COLUMNS = (
    ("clinicas", "id_version_plan"),
    ("tenant_requests", "id_version_plan"),
    ("tenant_subscriptions", "id_version_plan"),
    ("subscription_payments", "id_version_plan"),
)


def upgrade():
    # La restricción original de CU34 impedía auditar acciones globales de
    # tenants. La auditoría global ya era válida antes de CU34.
    op.drop_constraint(
        "ck_auditoria_global_catalogo", "auditoria", type_="check"
    )

    op.create_table(
        "legacy_plan_version_mappings",
        sa.Column("legacy_plan_version_id", sa.String(36), primary_key=True),
        sa.Column(
            "canonical_version_plan_id",
            sa.BigInteger(),
            sa.ForeignKey("versiones_plan.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    for table, column in _CANONICAL_COLUMNS:
        op.add_column(table, sa.Column(column, sa.BigInteger(), nullable=True))
        op.create_index(f"ix_{table}_{column}", table, [column])
        op.create_foreign_key(
            f"fk_{table}_{column}",
            table,
            "versiones_plan",
            [column],
            ["id"],
            ondelete="RESTRICT",
        )

    # Las referencias legacy quedan nullable durante la transición; las nuevas
    # contrataciones escriben exclusivamente la FK canónica.
    op.alter_column(
        "tenant_subscriptions",
        "id_plan_version",
        existing_type=sa.String(36),
        nullable=True,
    )
    op.alter_column(
        "subscription_payments",
        "id_plan_version",
        existing_type=sa.String(36),
        nullable=True,
    )

    # Preflight: la decisión de producto es mensual exclusivamente.
    non_monthly_subscriptions = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM tenant_subscriptions WHERE ciclo <> 'MONTHLY'")
    )
    non_monthly_payments = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM subscription_payments WHERE ciclo <> 'MONTHLY'")
    )
    if non_monthly_subscriptions or non_monthly_payments:
        raise RuntimeError(
            "La consolidación requiere que todas las suscripciones y pagos "
            "existentes tengan ciclo MONTHLY"
        )

    # Reutilizar una versión canónica con el mismo nombre cuando exista.
    op.execute(
        """
        INSERT INTO legacy_plan_version_mappings (
            legacy_plan_version_id, canonical_version_plan_id
        )
        SELECT pv.id_plan_version, vp.id
        FROM plan_versions pv
        JOIN planes p ON p.activo = TRUE
        JOIN versiones_plan vp ON vp.plan_id = p.id
         AND vp.numero = p.version_actual
         AND lower(vp.nombre) = lower(pv.nombre)
        ON CONFLICT (legacy_plan_version_id) DO NOTHING
        """
    )
    # Crear el catálogo canónico para cada legacy aún no mapeado.
    op.execute(
        """
        INSERT INTO planes (codigo, activo, version_actual)
        SELECT 'LEGACY_' || pv.id_plan_version, pv.estado = 'ACTIVO', 1
        FROM plan_versions pv
        WHERE NOT EXISTS (
            SELECT 1 FROM legacy_plan_version_mappings m
            WHERE m.legacy_plan_version_id = pv.id_plan_version
        )
        ON CONFLICT (codigo) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO versiones_plan (
            plan_id, numero, nombre, descripcion, precio_mensual, moneda,
            ciclo, servicios_incluidos, limite_medicos, limite_sedes,
            limite_consultas, tarifas_excedentes, demora_pago_dias, creado_por
        )
        SELECT p.id, 1, pv.nombre, left(pv.descripcion, 2000),
               pv.precio_mensual, 'BOB', 'MENSUAL', '[]'::json,
               pv.limite_medicos, NULL, pv.limite_consultas_mes, '[]'::json,
               7, COALESCE((
                   SELECT MIN(u.id_usuario) FROM usuarios u
                   JOIN roles r ON r.id_rol = u.id_rol
                   WHERE upper(r.nombre) = 'SUPER_ADMIN'
               ), (SELECT MIN(u.id_usuario) FROM usuarios u))
        FROM plan_versions pv
        JOIN planes p ON p.codigo = 'LEGACY_' || pv.id_plan_version
        WHERE NOT EXISTS (
            SELECT 1 FROM legacy_plan_version_mappings m
            WHERE m.legacy_plan_version_id = pv.id_plan_version
        )
        """
    )
    op.execute(
        """
        INSERT INTO legacy_plan_version_mappings (
            legacy_plan_version_id, canonical_version_plan_id
        )
        SELECT pv.id_plan_version, vp.id
        FROM plan_versions pv
        JOIN planes p ON p.codigo = 'LEGACY_' || pv.id_plan_version
        JOIN versiones_plan vp ON vp.plan_id = p.id AND vp.numero = 1
        ON CONFLICT (legacy_plan_version_id) DO NOTHING
        """
    )

    op.execute(
        """
        UPDATE tenant_subscriptions ts
        SET id_version_plan = m.canonical_version_plan_id
        FROM legacy_plan_version_mappings m
        WHERE ts.id_plan_version = m.legacy_plan_version_id
        """
    )
    op.execute(
        """
        UPDATE subscription_payments sp
        SET id_version_plan = m.canonical_version_plan_id
        FROM legacy_plan_version_mappings m
        WHERE sp.id_plan_version = m.legacy_plan_version_id
        """
    )
    op.execute(
        """
        UPDATE tenant_requests tr
        SET id_version_plan = m.canonical_version_plan_id
        FROM legacy_plan_version_mappings m
        WHERE tr.plan_version_id = m.legacy_plan_version_id
        """
    )
    op.execute(
        """
        UPDATE clinicas c
        SET id_version_plan = m.canonical_version_plan_id
        FROM legacy_plan_version_mappings m
        WHERE c.plan_id = m.legacy_plan_version_id
        """
    )

    op.create_check_constraint(
        "ck_tenant_subscriptions_ciclo_mensual",
        "tenant_subscriptions",
        "ciclo = 'MONTHLY'",
    )
    op.create_check_constraint(
        "ck_subscription_payments_ciclo_mensual",
        "subscription_payments",
        "ciclo = 'MONTHLY'",
    )


def downgrade():
    op.drop_constraint(
        "ck_subscription_payments_ciclo_mensual",
        "subscription_payments",
        type_="check",
    )
    op.drop_constraint(
        "ck_tenant_subscriptions_ciclo_mensual",
        "tenant_subscriptions",
        type_="check",
    )
    for table, column in reversed(_CANONICAL_COLUMNS):
        op.drop_constraint(f"fk_{table}_{column}", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_column(table, column)
    op.drop_table("legacy_plan_version_mappings")
    op.alter_column(
        "tenant_subscriptions",
        "id_plan_version",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.alter_column(
        "subscription_payments",
        "id_plan_version",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_auditoria_global_catalogo",
        "auditoria",
        "id_clinica IS NOT NULL OR COALESCE(tabla_afectada IN ('planes', 'versiones_plan'), FALSE)",
    )
