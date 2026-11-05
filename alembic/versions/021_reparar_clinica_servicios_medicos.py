"""Repara servicios médicos demo sin clínica asignada.

Los servicios 1 y 2 del seed histórico se crearon sin ``id_clinica`` aunque
sus horarios los vinculan de forma unívoca con la clínica 1. El directorio de
especialistas filtra por ``id_clinica`` para preservar el aislamiento
multitenant, por lo que esos servicios no llegaban a las tarjetas.

La migración solo completa servicios cuyos médicos vinculados pertenecen a
exactamente una clínica. No asigna servicios ambiguos ni huérfanos.
"""
from alembic import op
import sqlalchemy as sa


revision = "cu06_servicios_clinica_021"
down_revision = "cu34_consolidacion_020"
branch_labels = None
depends_on = None


_CREATE_AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS cu06_servicios_clinica_reparados (
    id_servicio BIGINT PRIMARY KEY,
    id_clinica BIGINT NOT NULL
)
"""

_BACKFILL_SQL = """
WITH clinicas_unicas AS (
    SELECT h.id_servicio, MIN(m.id_clinica) AS id_clinica
    FROM horarios_medicos h
    JOIN medicos m ON m.id_medico = h.id_medico
    WHERE m.id_clinica IS NOT NULL
    GROUP BY h.id_servicio
    HAVING COUNT(DISTINCT m.id_clinica) = 1
)
INSERT INTO cu06_servicios_clinica_reparados (id_servicio, id_clinica)
SELECT s.id_servicio, c.id_clinica
FROM servicios_medicos s
JOIN clinicas_unicas c ON c.id_servicio = s.id_servicio
WHERE s.id_clinica IS NULL
ON CONFLICT (id_servicio) DO NOTHING
"""

_UPDATE_SQL = """
UPDATE servicios_medicos s
SET id_clinica = r.id_clinica
FROM cu06_servicios_clinica_reparados r
WHERE s.id_servicio = r.id_servicio
  AND s.id_clinica IS NULL
"""


def upgrade():
    op.execute(sa.text(_CREATE_AUDIT_SQL))
    op.execute(sa.text(_BACKFILL_SQL))
    op.execute(sa.text(_UPDATE_SQL))

    # El servicio histórico 2 se documenta como teleconsulta y sus citas lo
    # utilizan como TELEMEDICINA, aunque el seed lo dejó como PRESENCIAL.
    op.execute(
        sa.text(
            """
            UPDATE servicios_medicos
            SET modalidad = 'TELECONSULTA'
            WHERE id_servicio = 2
              AND nombre = 'Consulta especializada'
            """
        )
    )


def downgrade():
    # Revierte únicamente los servicios reparados por esta migración. Si su
    # clínica cambió posteriormente, se conserva el valor nuevo para no
    # destruir una asignación válida realizada por otra operación.
    inspector = sa.inspect(op.get_bind())
    audit_table_exists = "cu06_servicios_clinica_reparados" in inspector.get_table_names()
    if audit_table_exists:
        op.execute(
            sa.text(
                """
                UPDATE servicios_medicos s
                SET id_clinica = NULL
                FROM cu06_servicios_clinica_reparados r
                WHERE s.id_servicio = r.id_servicio
                  AND s.id_clinica = r.id_clinica
                """
            )
        )
    else:
        # Compatibilidad con la primera versión de esta migración, que no
        # creó la tabla auxiliar. Solo revierte servicios con una única
        # clínica posible entre sus médicos vinculados.
        op.execute(
            sa.text(
                """
                WITH clinicas_unicas AS (
                    SELECT h.id_servicio, MIN(m.id_clinica) AS id_clinica
                    FROM horarios_medicos h
                    JOIN medicos m ON m.id_medico = h.id_medico
                    WHERE m.id_clinica IS NOT NULL
                    GROUP BY h.id_servicio
                    HAVING COUNT(DISTINCT m.id_clinica) = 1
                )
                UPDATE servicios_medicos s
                SET id_clinica = NULL
                FROM clinicas_unicas c
                WHERE s.id_servicio = c.id_servicio
                  AND s.id_clinica = c.id_clinica
                """
            )
        )
    op.execute(
        sa.text(
            """
            UPDATE servicios_medicos
            SET modalidad = 'PRESENCIAL'
            WHERE id_servicio = 2
              AND nombre = 'Consulta especializada'
            """
        )
    )
    op.execute(sa.text("DROP TABLE IF EXISTS cu06_servicios_clinica_reparados"))
