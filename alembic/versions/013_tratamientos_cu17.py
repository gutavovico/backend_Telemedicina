"""Crear persistencia y permisos de seguimiento terapéutico CU17.

Revision ID: cu17_tratamientos_013
Revises: f7a8b9c0d1e2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "cu17_tratamientos_013"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_VALUE = JSONB().with_variant(sa.JSON(), "sqlite")


def pk(name):
    return sa.Column(name, ID, primary_key=True, autoincrement=True)


def fk(name, target, nullable=False):
    return sa.Column(name, ID, sa.ForeignKey(target), nullable=nullable)


def clinic():
    return fk("id_clinica", "clinicas.id_clinica")


def timestamp(name, nullable=True, default=None):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=default)


def upgrade():
    op.create_table(
        "tratamientos", pk("id_tratamiento"), clinic(),
        fk("id_consulta", "consultas.id_consulta"), fk("id_receta", "recetas.id_receta", True),
        fk("id_diagnostico", "diagnosticos.id_diagnostico"), fk("id_paciente", "pacientes.id_paciente"),
        fk("id_medico", "medicos.id_medico"), sa.Column("fecha_inicio", sa.Date, nullable=False),
        sa.Column("fecha_fin", sa.Date, nullable=False), sa.Column("zona_horaria", sa.String(100), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False, server_default="ACTIVO"),
        sa.Column("notas", sa.Text), sa.Column("motivo_cierre", sa.Text),
        timestamp("created_at", False, sa.func.now()), timestamp("updated_at", False, sa.func.now()),
        sa.UniqueConstraint("id_clinica", "id_receta", name="uq_tratamiento_clinica_receta"),
        sa.CheckConstraint("fecha_fin >= fecha_inicio", name="ck_tratamiento_fechas"),
        sa.CheckConstraint("estado IN ('ACTIVO','FINALIZADO','SUSPENDIDO_POR_RECETA')", name="ck_tratamiento_estado"),
    )
    op.create_index("ix_tratamiento_paciente", "tratamientos", ["id_clinica", "id_paciente", "estado"])
    op.create_index("ix_tratamiento_medico", "tratamientos", ["id_clinica", "id_medico", "estado"])
    op.create_index("uq_tratamiento_consulta_sin_receta", "tratamientos", ["id_clinica", "id_consulta"], unique=True,
                    postgresql_where=sa.text("id_receta IS NULL"), sqlite_where=sa.text("id_receta IS NULL"))
    op.create_table(
        "tratamiento_medicamentos", pk("id_medicamento_plan"), clinic(),
        fk("id_tratamiento", "tratamientos.id_tratamiento"), fk("id_receta_detalle", "receta_detalle.id_receta_detalle"),
        sa.Column("medicamento_nombre", sa.String(200), nullable=False), sa.Column("dosis", sa.String(100), nullable=False),
        sa.Column("via_administracion", sa.String(30), nullable=False),
        sa.Column("frecuencia_texto_receta", sa.String(100), nullable=False),
        sa.Column("duracion_texto_receta", sa.String(100), nullable=False), sa.Column("indicaciones", sa.Text),
        sa.Column("fecha_inicio", sa.Date, nullable=False), sa.Column("fecha_fin", sa.Date, nullable=False),
        sa.Column("horas_locales", JSON_VALUE, nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"), timestamp("suspendido_desde"),
        sa.UniqueConstraint("id_clinica", "id_tratamiento", "id_receta_detalle", name="uq_tratamiento_medicamento_detalle"),
        sa.CheckConstraint("fecha_fin >= fecha_inicio", name="ck_tratamiento_medicamento_fechas"),
        sa.CheckConstraint("estado IN ('ACTIVO','SUSPENDIDO')", name="ck_tratamiento_medicamento_estado"),
    )
    op.create_index("ix_tratamiento_medicamento_plan", "tratamiento_medicamentos", ["id_clinica", "id_tratamiento"])
    op.create_table(
        "tratamiento_dosis", pk("id_dosis"), clinic(), fk("id_medicamento_plan", "tratamiento_medicamentos.id_medicamento_plan"),
        timestamp("programada_en_utc", False), sa.Column("estado", sa.String(20), nullable=False, server_default="PENDIENTE"),
        timestamp("efectiva_en_utc"), timestamp("registrada_en_utc"), timestamp("cancelada_en_utc"),
        timestamp("alertas_evaluadas_en_utc"), sa.Column("nota", sa.Text),
        sa.UniqueConstraint("id_clinica", "id_medicamento_plan", "programada_en_utc", name="uq_tratamiento_dosis_hora"),
        sa.CheckConstraint("estado IN ('PENDIENTE','INGERIDA','OMITIDA','POSPUESTA')", name="ck_tratamiento_dosis_estado"),
    )
    op.create_index("ix_tratamiento_dosis_programada", "tratamiento_dosis", ["id_clinica", "programada_en_utc", "estado"])
    op.create_index("ix_tratamiento_dosis_alertas", "tratamiento_dosis", ["id_clinica", "alertas_evaluadas_en_utc", "programada_en_utc"])
    op.create_table(
        "tratamiento_eventos", pk("id_evento"), clinic(), fk("id_tratamiento", "tratamientos.id_tratamiento"),
        fk("id_medicamento_plan", "tratamiento_medicamentos.id_medicamento_plan", True),
        fk("id_dosis", "tratamiento_dosis.id_dosis", True), sa.Column("accion", sa.String(50), nullable=False),
        sa.Column("estado_anterior", sa.String(30)), sa.Column("estado_nuevo", sa.String(30)),
        fk("id_usuario", "usuarios.id_usuario"), sa.Column("rol_actor", sa.String(100), nullable=False),
        sa.Column("direccion_ip", sa.String(45)), sa.Column("nota", sa.Text), timestamp("efectiva_en_utc"),
        timestamp("ocurrida_en_utc", False, sa.func.now()), sa.Column("idempotencia_hash", sa.String(64)),
        sa.Column("request_hash", sa.String(64)), sa.Column("respuesta_json", JSON_VALUE),
        sa.UniqueConstraint("id_clinica", "id_usuario", "id_dosis", "idempotencia_hash", name="uq_tratamiento_evento_idempotencia"),
    )
    op.create_index("ix_tratamiento_evento_plan", "tratamiento_eventos", ["id_clinica", "id_tratamiento", "ocurrida_en_utc"])
    op.create_table(
        "tratamiento_avisos", pk("id_aviso"), clinic(), fk("id_tratamiento", "tratamientos.id_tratamiento"),
        fk("id_dosis", "tratamiento_dosis.id_dosis"), fk("id_usuario", "usuarios.id_usuario"),
        sa.Column("tipo", sa.String(30), nullable=False), sa.Column("canal", sa.String(10), nullable=False),
        sa.Column("titulo", sa.String(200), nullable=False), sa.Column("mensaje", sa.Text, nullable=False),
        timestamp("programada_en_utc", False), sa.Column("estado", sa.String(15), nullable=False, server_default="PENDIENTE"),
        timestamp("enviada_en_utc"), timestamp("leida_en_utc"),
        sa.Column("intentos", sa.Integer, nullable=False, server_default="0"), sa.Column("ultimo_error", sa.String(100)),
        timestamp("created_at", False, sa.func.now()),
        sa.UniqueConstraint("id_clinica", "id_dosis", "id_usuario", "tipo", "canal", name="uq_cu17_aviso"),
        sa.CheckConstraint("tipo IN ('RECORDATORIO','OMISION','RIESGO_ABANDONO')", name="ck_cu17_aviso_tipo"),
        sa.CheckConstraint("canal IN ('WEB','PUSH')", name="ck_cu17_aviso_canal"),
        sa.CheckConstraint("estado IN ('PENDIENTE','ENVIADO','FALLIDO')", name="ck_cu17_aviso_estado"),
    )
    op.create_index("ix_cu17_aviso_usuario", "tratamiento_avisos", ["id_clinica", "id_usuario", "canal", "created_at"])
    op.create_index("ix_cu17_aviso_pendiente", "tratamiento_avisos", ["id_clinica", "canal", "estado", "programada_en_utc"])
    op.create_table(
        "tratamiento_dispositivos", pk("id_dispositivo"), clinic(), fk("id_usuario", "usuarios.id_usuario"),
        sa.Column("token_cifrado", sa.Text, nullable=False), sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("plataforma", sa.String(10), nullable=False), sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        timestamp("created_at", False, sa.func.now()), timestamp("updated_at", False, sa.func.now()),
        sa.UniqueConstraint("id_clinica", "id_usuario", "token_hash", name="uq_cu17_dispositivo"),
        sa.CheckConstraint("plataforma IN ('ANDROID','IOS')", name="ck_cu17_dispositivo_plataforma"),
    )
    op.create_index("ix_cu17_dispositivo_usuario", "tratamiento_dispositivos", ["id_clinica", "id_usuario", "activo"])
    op.create_table(
        "tratamiento_entregas_push", pk("id_entrega"), clinic(), fk("id_aviso", "tratamiento_avisos.id_aviso"),
        fk("id_dispositivo", "tratamiento_dispositivos.id_dispositivo"),
        sa.Column("estado", sa.String(15), nullable=False, server_default="PENDIENTE"),
        sa.Column("intentos", sa.Integer, nullable=False, server_default="0"), timestamp("proximo_intento_en_utc"),
        sa.Column("ultimo_error", sa.String(100)), timestamp("enviada_en_utc"),
        sa.UniqueConstraint("id_clinica", "id_aviso", "id_dispositivo", name="uq_cu17_entrega_push"),
        sa.CheckConstraint("estado IN ('PENDIENTE','ENVIADO','FALLIDO')", name="ck_cu17_entrega_estado"),
    )
    op.create_index("ix_cu17_entrega_pendiente", "tratamiento_entregas_push", ["id_clinica", "estado", "proximo_intento_en_utc"])
    op.create_table(
        "tratamiento_cursores",
        sa.Column("id_clinica", ID, sa.ForeignKey("clinicas.id_clinica"), primary_key=True),
        sa.Column("id_tratamiento", ID, sa.ForeignKey("tratamientos.id_tratamiento"), primary_key=True),
        sa.Column("siguiente_fecha", sa.Date, nullable=False),
        timestamp("updated_at", False, sa.func.now()),
    )

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("""CREATE FUNCTION cu17_eventos_inmutables() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Los eventos CU17 son inmutables'; END; $$ LANGUAGE plpgsql""")
        op.execute("CREATE TRIGGER cu17_eventos_inmutables BEFORE UPDATE OR DELETE ON tratamiento_eventos FOR EACH ROW EXECUTE FUNCTION cu17_eventos_inmutables()")
    elif dialect == "sqlite":
        op.execute("CREATE TRIGGER cu17_eventos_no_update BEFORE UPDATE ON tratamiento_eventos BEGIN SELECT RAISE(ABORT, 'Los eventos CU17 son inmutables'); END")
        op.execute("CREATE TRIGGER cu17_eventos_no_delete BEFORE DELETE ON tratamiento_eventos BEGIN SELECT RAISE(ABORT, 'Los eventos CU17 son inmutables'); END")

    permissions = {
        "treatments:read": "Consultar tratamientos",
        "treatments:write": "Gestionar tratamientos",
        "treatments:dose:record": "Registrar dosis propias",
        "treatments:notify:read": "Consultar avisos propios",
    }
    for name, description in permissions.items():
        op.execute(sa.text("INSERT INTO permisos (nombre,descripcion,modulo,accion,estado) "
                           "SELECT :name,:description,'treatments',:action,'ACTIVO' "
                           "WHERE NOT EXISTS (SELECT 1 FROM permisos WHERE nombre=:name)")
                   .bindparams(name=name, description=description, action=name.split(":", 1)[1]))
    for role, names in {
        "MEDICO": ("treatments:read", "treatments:write", "treatments:notify:read"),
        "PACIENTE": ("treatments:read", "treatments:dose:record", "treatments:notify:read"),
    }.items():
        for name in names:
            op.execute(sa.text("INSERT INTO rol_permisos (id_rol,id_permiso) "
                               "SELECT r.id_rol,p.id_permiso FROM roles r JOIN permisos p ON p.nombre=:name "
                               "WHERE UPPER(r.nombre)=:role AND NOT EXISTS "
                               "(SELECT 1 FROM rol_permisos rp WHERE rp.id_rol=r.id_rol AND rp.id_permiso=p.id_permiso)")
                       .bindparams(role=role, name=name))


def downgrade():
    raise RuntimeError("CU17 conserva datos clínicos; la reversión operativa desactiva las rutas y el trabajo, sin borrar tablas")
