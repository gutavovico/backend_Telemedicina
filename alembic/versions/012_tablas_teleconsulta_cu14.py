"""Crear tablas y columnas para CU14 Ejecución de Teleconsulta Médica Remota (WebRTC)

Revision ID: f4a5b6c7d8e9
Revises: 11411f333d08
Create Date: 2026-10-30 17:48:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "11411f333d08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Crear tabla sesiones_teleconsulta para CU14
    op.execute("""
        CREATE TABLE IF NOT EXISTS sesiones_teleconsulta (
            id_teleconsulta BIGSERIAL PRIMARY KEY,
            id_clinica BIGINT NOT NULL REFERENCES clinicas(id_clinica) ON DELETE CASCADE,
            id_cita BIGINT NOT NULL REFERENCES citas(id_cita) ON DELETE CASCADE,
            id_medico BIGINT NOT NULL REFERENCES medicos(id_medico) ON DELETE CASCADE,
            id_paciente BIGINT NOT NULL REFERENCES pacientes(id_paciente) ON DELETE CASCADE,
            codigo_ficha VARCHAR(50) NOT NULL DEFAULT 'FICHA-CU14',
            estado VARCHAR(30) NOT NULL DEFAULT 'EN_ESPERA',
            posicion_fila INTEGER NOT NULL DEFAULT 1,
            pacientes_antes INTEGER NOT NULL DEFAULT 0,
            tiempo_estimado_minutos INTEGER NOT NULL DEFAULT 10,
            duracion_segundos INTEGER NOT NULL DEFAULT 0,
            calidad_red VARCHAR(30) NOT NULL DEFAULT 'HD 1080p',
            cifrado_activo BOOLEAN NOT NULL DEFAULT TRUE,
            doctor_conectado BOOLEAN NOT NULL DEFAULT FALSE,
            paciente_conectado BOOLEAN NOT NULL DEFAULT FALSE,
            compartiendo_pantalla BOOLEAN NOT NULL DEFAULT FALSE,
            camara_activa_paciente BOOLEAN NOT NULL DEFAULT TRUE,
            microfono_activo_paciente BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_inicio TIMESTAMPTZ NULL,
            fecha_fin TIMESTAMPTZ NULL,
            motivo_evolucion TEXT NULL,
            examen_fisico TEXT NULL,
            diagnostico_cie10 VARCHAR(255) NULL,
            plan_tratamiento TEXT NULL,
            presion_arterial VARCHAR(50) NULL,
            frecuencia_cardiaca VARCHAR(50) NULL,
            peso_kg VARCHAR(50) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_teleconsulta_tenant ON sesiones_teleconsulta (id_clinica, id_cita);
        CREATE INDEX IF NOT EXISTS idx_teleconsulta_medico ON sesiones_teleconsulta (id_medico, estado);
        CREATE INDEX IF NOT EXISTS idx_teleconsulta_paciente ON sesiones_teleconsulta (id_paciente, estado);
    """)

    # 2. Crear tabla de verificaciones de equipo y periféricos (cámara, micrófono, conexión)
    op.execute("""
        CREATE TABLE IF NOT EXISTS verificaciones_equipo_teleconsulta (
            id_verificacion BIGSERIAL PRIMARY KEY,
            id_teleconsulta BIGINT NOT NULL REFERENCES sesiones_teleconsulta(id_teleconsulta) ON DELETE CASCADE,
            camara_verificada BOOLEAN NOT NULL DEFAULT TRUE,
            microfono_verificado BOOLEAN NOT NULL DEFAULT TRUE,
            conexion_calidad VARCHAR(50) NOT NULL DEFAULT 'Buena',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_verificacion_teleconsulta ON verificaciones_equipo_teleconsulta (id_teleconsulta);
    """)

    # 3. Agregar referencia opcional en citas a id_teleconsulta si no existe
    op.execute("""
        ALTER TABLE citas ADD COLUMN IF NOT EXISTS id_teleconsulta BIGINT REFERENCES sesiones_teleconsulta(id_teleconsulta) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_citas_id_teleconsulta ON citas(id_teleconsulta);
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE citas DROP COLUMN IF EXISTS id_teleconsulta;")
    op.execute("DROP TABLE IF EXISTS verificaciones_equipo_teleconsulta;")
    op.execute("DROP TABLE IF EXISTS sesiones_teleconsulta;")
