"""CU20: Dispositivos autorizados, Outbox transaccional y extensión de bandeja de notificaciones."""

from alembic import op
import sqlalchemy as sa

revision = "cu20_notificaciones_017"
down_revision = "cu34_catalogo_016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dispositivos_autorizados",
        sa.Column("id_dispositivo", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("id_clinica", sa.BigInteger(), sa.ForeignKey("clinicas.id_clinica"), nullable=True),
        sa.Column("id_usuario", sa.BigInteger(), sa.ForeignKey("usuarios.id_usuario"), nullable=False),
        sa.Column("rol_usuario", sa.String(30), nullable=True),
        sa.Column("canal", sa.String(12), nullable=False),
        sa.Column("dispositivo_id", sa.String(64), nullable=False),
        sa.Column("push_destino_cifrado", sa.LargeBinary(), nullable=True),
        sa.Column("push_destino_hash", sa.String(64), nullable=True),
        sa.Column("estado", sa.String(16), nullable=False, server_default="ACTIVO"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revocado_en", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("id_usuario", "canal", "dispositivo_id", name="uq_disp_usr_canal_cu20"),
        sa.CheckConstraint("canal IN ('PWA', 'FLUTTER')", name="ck_disp_canal_cu20"),
        sa.CheckConstraint("estado IN ('ACTIVO', 'REVOCADO')", name="ck_disp_estado_cu20"),
    )
    op.create_index("ix_dispositivos_usuario_activo", "dispositivos_autorizados", ["id_usuario", "estado"])
    op.create_index("ix_dispositivos_clinica_usuario", "dispositivos_autorizados", ["id_clinica", "id_usuario"])

    op.create_table(
        "eventos_outbox",
        sa.Column("id_evento", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("id_clinica", sa.BigInteger(), sa.ForeignKey("clinicas.id_clinica"), nullable=True),
        sa.Column("id_usuario_destino", sa.BigInteger(), sa.ForeignKey("usuarios.id_usuario"), nullable=False),
        sa.Column("recurso_tipo", sa.String(50), nullable=False),
        sa.Column("recurso_id", sa.String(64), nullable=False),
        sa.Column("transicion", sa.String(60), nullable=False),
        sa.Column("canal_objetivo", sa.String(20), nullable=False, server_default="MULTI"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dispositivo_id", sa.String(64), nullable=True),
        sa.Column("idempotency_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="PENDIENTE"),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_intentos", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("proximo_intento_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("entregado_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE', 'REINTENTO', 'ENVIADO', 'FALLIDO', 'FALLIDO_PARCIAL', 'SIN_DESTINOS')",
            name="ck_outbox_estado_cu20",
        ),
    )
    op.create_index("ix_outbox_pendiente", "eventos_outbox", ["estado", "proximo_intento_en", "creado_en"])
    op.create_index("ix_outbox_idempotencia", "eventos_outbox", ["idempotency_hash"])
    op.create_index("ix_outbox_clinica", "eventos_outbox", ["id_clinica", "estado"])

    # Extensión aditiva y compatible hacia atrás de la tabla `notificaciones`
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notificaciones" in inspector.get_table_names():
        existentes = {col["name"] for col in inspector.get_columns("notificaciones")}
        columnas_nuevas = [
            ("id_clinica", sa.Column("id_clinica", sa.BigInteger(), sa.ForeignKey("clinicas.id_clinica"), nullable=True)),
            ("outbox_id", sa.Column("outbox_id", sa.BigInteger(), sa.ForeignKey("eventos_outbox.id_evento"), nullable=True)),
            ("rol_destinatario", sa.Column("rol_destinatario", sa.String(30), nullable=True)),
            ("categoria", sa.Column("categoria", sa.String(30), nullable=False, server_default="SISTEMA")),
            ("canal_badge", sa.Column("canal_badge", sa.String(30), nullable=True)),
            ("recurso_tipo", sa.Column("recurso_tipo", sa.String(50), nullable=True)),
            ("recurso_id", sa.Column("recurso_id", sa.String(64), nullable=True)),
            ("enlace_accion", sa.Column("enlace_accion", sa.String(255), nullable=True)),
            ("payload_extra", sa.Column("payload_extra", sa.JSON(), nullable=True)),
            ("created_at", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())),
        ]
        for nombre, col in columnas_nuevas:
            if nombre not in existentes:
                op.add_column("notificaciones", col)


def downgrade():
    op.drop_table("eventos_outbox")
    op.drop_table("dispositivos_autorizados")
