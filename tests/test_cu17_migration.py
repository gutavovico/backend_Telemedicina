"""Prueba la migración CU17 sin conectarse a la base de datos de la aplicación."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from app.modules.medical_records.tratamientos.models import (
    Tratamiento, TratamientoMedicamento, TratamientoDosis, TratamientoEvento,
)
from app.modules.medical_records.tratamientos.avisos_models import (
    TratamientoAviso, TratamientoDispositivo, TratamientoEntregaPush, TratamientoCursor,
)


def test_migracion_crea_permisos_y_protege_eventos():
    ruta = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "013_tratamientos_cu17.py"
    spec = importlib.util.spec_from_file_location("migration_cu17", ruta)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        for table, key in (
            ("clinicas", "id_clinica"), ("consultas", "id_consulta"),
            ("recetas", "id_receta"), ("diagnosticos", "id_diagnostico"),
            ("pacientes", "id_paciente"), ("medicos", "id_medico"),
            ("receta_detalle", "id_receta_detalle"), ("usuarios", "id_usuario"),
        ):
            conn.exec_driver_sql(f"CREATE TABLE {table} ({key} INTEGER PRIMARY KEY)")
            conn.exec_driver_sql(f"INSERT INTO {table} ({key}) VALUES (1)")
        conn.exec_driver_sql("CREATE TABLE roles (id_rol INTEGER PRIMARY KEY, nombre TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO roles VALUES (1,'MEDICO'),(2,'PACIENTE'),(3,'RECEPCION')")
        conn.exec_driver_sql("CREATE TABLE permisos (id_permiso INTEGER PRIMARY KEY, nombre TEXT, descripcion TEXT, modulo TEXT, accion TEXT, estado TEXT)")
        conn.exec_driver_sql("CREATE TABLE rol_permisos (id_rol INTEGER, id_permiso INTEGER, PRIMARY KEY(id_rol,id_permiso))")
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        inspector = inspect(conn)
        for model in (Tratamiento, TratamientoMedicamento, TratamientoDosis, TratamientoEvento,
                      TratamientoAviso, TratamientoDispositivo, TratamientoEntregaPush, TratamientoCursor):
            expected_cols = {column.name for column in model.__table__.columns}
            if model is TratamientoDosis:
                expected_cols -= {"generacion"}  # Columna 'generacion' es incorporada en migracion 014
            assert {column["name"] for column in inspector.get_columns(model.__tablename__)} == expected_cols
        actual = conn.execute(text("SELECT r.nombre,p.nombre FROM roles r JOIN rol_permisos rp ON rp.id_rol=r.id_rol JOIN permisos p ON p.id_permiso=rp.id_permiso")).all()
        assert ("MEDICO", "treatments:write") in actual
        assert ("PACIENTE", "treatments:dose:record") in actual
        assert not any(role == "RECEPCION" for role, _ in actual)
        conn.exec_driver_sql("INSERT INTO tratamientos (id_tratamiento,id_clinica,id_consulta,id_diagnostico,id_paciente,id_medico,fecha_inicio,fecha_fin,zona_horaria) VALUES (1,1,1,1,1,1,'2026-01-01','2026-01-31','America/La_Paz')")
        conn.exec_driver_sql("INSERT INTO tratamiento_eventos (id_clinica,id_tratamiento,accion,id_usuario,rol_actor) VALUES (1,1,'CREAR',1,'MEDICO')")
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql("UPDATE tratamiento_eventos SET accion='EDITAR'")
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql("DELETE FROM tratamiento_eventos")
        assert conn.exec_driver_sql("SELECT accion FROM tratamiento_eventos").scalar_one() == "CREAR"
        with pytest.raises(RuntimeError):
            migration.downgrade()
    engine.dispose()


def test_migracion_014_operaciones_dosis_upgrade_y_downgrade_protegido():
    """Verifica que la migración 014 agrega columna 'generacion', preserva historial y rechaza downgrade destructivo."""
    ruta_013 = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "013_tratamientos_cu17.py"
    spec_013 = importlib.util.spec_from_file_location("migration_013", ruta_013)
    migration_013 = importlib.util.module_from_spec(spec_013)
    spec_013.loader.exec_module(migration_013)

    ruta_014 = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "014_operaciones_dosis_cu17.py"
    spec_014 = importlib.util.spec_from_file_location("migration_014", ruta_014)
    migration_014 = importlib.util.module_from_spec(spec_014)
    spec_014.loader.exec_module(migration_014)

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        for table, key in (
            ("clinicas", "id_clinica"), ("consultas", "id_consulta"),
            ("recetas", "id_receta"), ("diagnosticos", "id_diagnostico"),
            ("pacientes", "id_paciente"), ("medicos", "id_medico"),
            ("receta_detalle", "id_receta_detalle"), ("usuarios", "id_usuario"),
        ):
            conn.exec_driver_sql(f"CREATE TABLE {table} ({key} INTEGER PRIMARY KEY)")
            conn.exec_driver_sql(f"INSERT INTO {table} ({key}) VALUES (1)")
        conn.exec_driver_sql("CREATE TABLE roles (id_rol INTEGER PRIMARY KEY, nombre TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO roles VALUES (1,'MEDICO'),(2,'PACIENTE'),(3,'RECEPCION')")
        conn.exec_driver_sql("CREATE TABLE permisos (id_permiso INTEGER PRIMARY KEY, nombre TEXT, descripcion TEXT, modulo TEXT, accion TEXT, estado TEXT)")
        conn.exec_driver_sql("CREATE TABLE rol_permisos (id_rol INTEGER, id_permiso INTEGER, PRIMARY KEY(id_rol,id_permiso))")

        # Ejecutar primero migración 013 base
        migration_013.op = Operations(MigrationContext.configure(conn))
        migration_013.upgrade()

        # Insertar registros previos para validar backfill a tratamiento_operaciones_dosis
        conn.exec_driver_sql("INSERT INTO tratamientos (id_tratamiento,id_clinica,id_consulta,id_diagnostico,id_paciente,id_medico,fecha_inicio,fecha_fin,zona_horaria) VALUES (1,1,1,1,1,1,'2026-01-01','2026-01-31','America/La_Paz')")
        conn.exec_driver_sql("INSERT INTO tratamiento_medicamentos (id_medicamento_plan,id_clinica,id_tratamiento,id_receta_detalle,medicamento_nombre,dosis,via_administracion,frecuencia_texto_receta,duracion_texto_receta,fecha_inicio,fecha_fin,horas_locales) VALUES (1,1,1,1,'Paracetamol','500mg','ORAL','8h','3d','2026-01-01','2026-01-03','[\"08:00\"]')")
        conn.exec_driver_sql("INSERT INTO tratamiento_dosis (id_dosis,id_clinica,id_medicamento_plan,programada_en_utc,estado) VALUES (1,1,1,'2026-01-01 12:00:00','INGERIDA')")
        conn.exec_driver_sql("""
            INSERT INTO tratamiento_eventos (
                id_clinica, id_tratamiento, id_dosis, accion, id_usuario, rol_actor,
                idempotencia_hash, request_hash, respuesta_json, ocurrida_en_utc
            ) VALUES (
                1, 1, 1, 'REGISTRAR_DOSIS', 1, 'PACIENTE',
                'hash_idemp_previo', 'hash_req_previo', '{"adherencia": 100}', '2026-01-01 12:05:00'
            )
        """)

        # Ejecutar migración 014
        migration_014.op = Operations(MigrationContext.configure(conn))
        migration_014.upgrade()

        inspector = inspect(conn)

        # 1. Validar que tratamiento_dosis ahora tiene columna 'generacion'
        cols_dosis = {c["name"] for c in inspector.get_columns("tratamiento_dosis")}
        assert "generacion" in cols_dosis, "Columna 'generacion' no fue agregada a tratamiento_dosis"

        # 2. Validar que tratamiento_operaciones_dosis fue creada con columna 'generacion' y campos requeridos
        cols_op = {c["name"] for c in inspector.get_columns("tratamiento_operaciones_dosis")}
        assert "generacion" in cols_op, "Columna 'generacion' no fue creada en tratamiento_operaciones_dosis"
        for required_col in ("id_operacion", "id_clinica", "id_tratamiento", "id_dosis", "id_usuario",
                             "idempotencia_hash", "request_hash", "estado", "respuesta_json", "error_detail",
                             "created_at", "updated_at"):
            assert required_col in cols_op, f"Columna {required_col} falta en tratamiento_operaciones_dosis"

        # 3. Validar que el backfill preservó la toma previa en tratamiento_operaciones_dosis
        op_row = conn.execute(text("SELECT id_clinica, id_dosis, id_usuario, generacion, estado, idempotencia_hash, request_hash FROM tratamiento_operaciones_dosis WHERE idempotencia_hash = 'hash_idemp_previo'")).mappings().one()
        assert op_row["id_clinica"] == 1
        assert op_row["id_dosis"] == 1
        assert op_row["generacion"] == 1
        assert op_row["estado"] == "CONFIRMADA"
        assert op_row["request_hash"] == "hash_req_previo"

        # 4. Validar que downgrade() lanza RuntimeError y no borra tablas ni datos clínicos
        with pytest.raises(RuntimeError) as exc_info:
            migration_014.downgrade()

        assert "CU17 conserva datos clínicos e historial de operaciones" in str(exc_info.value)

        # Verificar que la tabla no fue borrada y los registros siguen intactos
        inspector_after = inspect(conn)
        tables = inspector_after.get_table_names()
        assert "tratamiento_operaciones_dosis" in tables
        assert "tratamiento_eventos" in tables
        assert "tratamiento_dosis" in tables

        count_ops = conn.execute(text("SELECT count(*) FROM tratamiento_operaciones_dosis")).scalar()
        assert count_ops == 1
        count_eventos = conn.execute(text("SELECT count(*) FROM tratamiento_eventos")).scalar()
        assert count_eventos >= 1

    engine.dispose()
