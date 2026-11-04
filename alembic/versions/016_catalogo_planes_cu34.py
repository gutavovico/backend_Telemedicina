"""CU34: catálogo global e historial inmutable; auditoría en la misma transacción."""
from alembic import op
import sqlalchemy as sa

revision = "cu34_catalogo_016"
down_revision = "cu17_backup_merge_015"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("auditoria", "id_clinica", existing_type=sa.BigInteger(), nullable=True)
    op.create_check_constraint("ck_auditoria_global_catalogo", "auditoria",
        "id_clinica IS NOT NULL OR COALESCE(tabla_afectada IN ('planes', 'versiones_plan'), FALSE)")
    op.create_table("planes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("codigo", sa.String(50), nullable=False, unique=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("version_actual", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version_actual >= 1", name="ck_planes_version_positiva"))
    op.create_table("versiones_plan",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("plan_id", sa.BigInteger(), sa.ForeignKey("planes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("descripcion", sa.String(2000)),
        sa.Column("precio_mensual", sa.Numeric(14, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False),
        sa.Column("ciclo", sa.String(7), nullable=False),
        sa.Column("servicios_incluidos", sa.JSON(), nullable=False),
        sa.Column("limite_medicos", sa.Integer()),
        sa.Column("limite_sedes", sa.Integer()),
        sa.Column("limite_consultas", sa.Integer()),
        sa.Column("tarifas_excedentes", sa.JSON(), nullable=False),
        sa.Column("demora_pago_dias", sa.Integer(), nullable=False),
        sa.Column("creado_por", sa.BigInteger(), sa.ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plan_id", "numero", name="uq_versiones_plan_numero"),
        sa.CheckConstraint("numero >= 1", name="ck_versiones_plan_numero"),
        sa.CheckConstraint("precio_mensual >= 0 AND precio_mensual <= 999999999999.99", name="ck_versiones_plan_precio"),
        sa.CheckConstraint("moneda = 'BOB' AND ciclo = 'MENSUAL'", name="ck_versiones_plan_moneda_ciclo"),
        sa.CheckConstraint("limite_medicos IS NULL OR limite_medicos >= 0", name="ck_versiones_plan_medicos"),
        sa.CheckConstraint("limite_sedes IS NULL OR limite_sedes >= 0", name="ck_versiones_plan_sedes"),
        sa.CheckConstraint("limite_consultas IS NULL OR limite_consultas >= 0", name="ck_versiones_plan_consultas"),
        sa.CheckConstraint("demora_pago_dias >= 0", name="ck_versiones_plan_demora"))
    op.execute("""CREATE FUNCTION cu34_version_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Las versiones del catálogo son inmutables'; END; $$""")
    op.execute("""CREATE TRIGGER cu34_version_inmutable BEFORE UPDATE OR DELETE ON versiones_plan
        FOR EACH ROW EXECUTE FUNCTION cu34_version_inmutable()""")


def downgrade():
    # Never silently discard historical conditions or global audit events.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM versiones_plan) OR EXISTS(SELECT 1 FROM auditoria WHERE id_clinica IS NULL)")):
        raise RuntimeError("CU34 contiene historial. El downgrade requiere un plan explícito de preservación de datos.")
    op.drop_table("versiones_plan")
    op.execute("DROP FUNCTION cu34_version_inmutable()")
    op.drop_table("planes")
    op.drop_constraint("ck_auditoria_global_catalogo", "auditoria", type_="check")
    op.alter_column("auditoria", "id_clinica", existing_type=sa.BigInteger(), nullable=False)
