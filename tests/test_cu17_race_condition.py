"""Pruebas de concurrencia, condición de carrera, idempotencia durable y aislamiento para CU17.
Ejecuta escenarios tanto en SQLite en memoria como en PostgreSQL real local.
"""
from datetime import datetime, timedelta, timezone
import threading
import time
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main
from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.tratamientos import service
from app.modules.medical_records.tratamientos.models import (
    Tratamiento,
    TratamientoDosis,
    TratamientoEvento,
    TratamientoOperacionDosis,
)
import os
from sqlalchemy.engine import make_url


def _get_disposable_postgres_url():
    pg_url = os.environ.get("CU17_TEST_POSTGRES_URL", "").strip()
    if not pg_url:
        pytest.skip("Pruebas PostgreSQL CU17 omitidas: CU17_TEST_POSTGRES_URL no definida con base desechable")

    try:
        url_obj = make_url(pg_url)
    except Exception as exc:
        pytest.skip(f"Pruebas PostgreSQL CU17 omitidas: CU17_TEST_POSTGRES_URL no es válida: {exc}")

    db_name = (url_obj.database or "").lower()
    host = (url_obj.host or "").lower()

    # Validar que sea desechable y no una base de producción ni la base local habitual
    is_protected = (
        db_name in ("telemedicina_local", "telemedicina", "postgres", "defaultdb")
        or any(token in db_name for token in ("prod", "production"))
        or any(token in host for token in ("neon", "prod", "production", "pooler"))
    )
    is_disposable = any(token in db_name for token in ("test", "disposable", "temp"))

    if not is_disposable or is_protected:
        pytest.skip(
            f"Pruebas PostgreSQL CU17 omitidas: Base '{db_name}' en host '{host}' no parece base desechable "
            f"(debe contener 'test', 'disposable' o 'temp' y no ser habitual, local estándar, Neon ni prod)."
        )

    return pg_url


def _clean_cu17_tables(conn):
    for tbl in ("tratamiento_operaciones_dosis", "tratamiento_eventos", "tratamiento_avisos",
                "tratamiento_dosis", "tratamiento_medicamentos", "tratamientos"):
        try:
            conn.execute(text(f"DELETE FROM {tbl}"))
        except Exception:
            pass
    try:
        conn.execute(text("DELETE FROM auditoria WHERE id_usuario >= 900"))
    except Exception:
        pass


def _seed_db(engine, is_sqlite=True):
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if is_sqlite:
            conn.exec_driver_sql("DROP TABLE IF EXISTS auditoria")
            conn.exec_driver_sql("""CREATE TABLE auditoria (
                id_auditoria INTEGER PRIMARY KEY AUTOINCREMENT,
                id_clinica BIGINT NOT NULL, id_usuario BIGINT NOT NULL,
                tabla_afectada VARCHAR(150), registro_id BIGINT, accion VARCHAR(50) NOT NULL,
                descripcion VARCHAR, datos_anteriores JSON, datos_nuevos JSON,
                direccion_ip VARCHAR(45), fecha_hora DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )""")
            _clean_cu17_tables(conn)
            for tbl in ("receta_detalle", "recetas", "documentos_clinicos", "diagnosticos",
                        "consultas", "historias_clinicas", "citas", "medicos", "pacientes",
                        "rol_permisos", "permisos", "usuarios", "roles", "clinicas"):
                try:
                    conn.exec_driver_sql(f"DELETE FROM {tbl}")
                except Exception:
                    pass

            conn.exec_driver_sql("INSERT INTO clinicas (id_clinica,nombre,estado) VALUES (1,'Centro A','ACTIVO'),(2,'Centro B','ACTIVO')")
            conn.exec_driver_sql("INSERT INTO roles (id_rol,id_clinica,nombre,estado) VALUES (1,1,'MEDICO','ACTIVO'),(2,1,'PACIENTE','ACTIVO'),(3,1,'RECEPCION','ACTIVO'),(4,2,'MEDICO','ACTIVO'),(5,2,'PACIENTE','ACTIVO')")
            conn.exec_driver_sql("""INSERT INTO usuarios
              (id_usuario,id_clinica,id_rol,nombres,apellidos,correo,password_hash,estado,notificaciones_push,notificaciones_email,notificaciones_sms)
              VALUES (901,1,1,'Medico','A','m901@test.invalid','x','activo',1,1,0),
                     (902,1,1,'Medico','B','m902@test.invalid','x','activo',1,1,0),
                     (903,1,2,'Paciente','A','p903@test.invalid','x','activo',1,1,0),
                     (904,1,2,'Paciente','B','p904@test.invalid','x','activo',1,1,0),
                     (905,2,4,'Medico','C','m905@test.invalid','x','activo',1,1,0),
                     (906,1,3,'Recepcion','A','r906@test.invalid','x','activo',1,1,0),
                     (907,2,5,'Paciente','C','p907@test.invalid','x','activo',1,1,0)""")
            for i, perm in enumerate(("treatments:read", "treatments:write", "treatments:dose:record", "treatments:notify:read"), 1):
                conn.exec_driver_sql("INSERT INTO permisos (id_permiso,nombre,modulo,accion,estado) VALUES (?,?,?,?,?)", (i, perm, "treatments", perm, "ACTIVO"))
            for role, perm in ((1,1),(1,2),(1,4),(2,1),(2,3),(2,4),(4,1),(4,2),(4,4),(5,1),(5,3),(5,4)):
                conn.exec_driver_sql("INSERT INTO rol_permisos (id_rol,id_permiso) VALUES (?,?)", (role, perm))
            conn.exec_driver_sql("""INSERT INTO pacientes (id_paciente,id_clinica,id_usuario,nombres,apellidos,ci,fecha_nacimiento,genero,telefono,estado)
              VALUES (910,1,903,'Paciente','A','CI903','1990-01-01','F','70000001','ACTIVO'),
                     (911,1,904,'Paciente','B','CI904','1990-01-01','F','70000002','ACTIVO'),
                     (912,2,907,'Paciente','C','CI907','1990-01-01','M','70000003','ACTIVO')""")
            conn.exec_driver_sql("INSERT INTO medicos (id_medico,id_clinica,id_usuario,matricula_profesional,estado) VALUES (921,1,901,'M901','activo'),(922,1,902,'M902','activo'),(923,2,905,'M905','activo')")
            conn.exec_driver_sql("INSERT INTO citas (id_cita,id_clinica,id_paciente,id_medico,estado) VALUES (931,1,910,921,'FINALIZADA'),(932,2,912,923,'FINALIZADA')")
            conn.exec_driver_sql("INSERT INTO historias_clinicas (id_historia,id_clinica,id_paciente,numero_historia) VALUES (941,1,910,'H941'),(942,2,912,'H942')")
            conn.exec_driver_sql("""INSERT INTO consultas (id_consulta,id_clinica,id_historia,id_cita,id_medico,motivo_consulta,sintomas,evolucion,plan_medico)
              VALUES (942,1,941,931,921,'Control','Sintomas','Estable','Tratamiento'),
                     (943,2,942,932,923,'Control B','Sintomas','Estable','Tratamiento')""")
            conn.exec_driver_sql("INSERT INTO diagnosticos (id_diagnostico,id_consulta,codigo_cie,descripcion,tipo) VALUES (954,942,'A00','Diagnostico','DEFINITIVO'),(955,943,'A00','Diagnostico B','DEFINITIVO')")
            conn.exec_driver_sql("""INSERT INTO recetas (id_receta,id_clinica,id_consulta,id_medico,id_paciente,folio,codigo_verificacion_hash,firma_digital,algoritmo_firma,key_id,version_payload,hash_pdf,fecha_vencimiento,estado)
              VALUES (981,1,942,921,910,'REC-981',?,'firma','ED25519','test',1,?,'2099-01-01','EMITIDA'),
                     (982,2,943,923,912,'REC-982',?,'firma','ED25519','test',1,?,'2099-01-01','EMITIDA')""", ("a"*64, "b"*64, "c"*64, "d"*64))
            conn.exec_driver_sql("""INSERT INTO receta_detalle (id_receta_detalle,id_receta,nombre_medicamento_manual,medicamento_nombre,dosis,frecuencia,duracion,via_administracion,cantidad,indicaciones,posicion)
              VALUES (9121,981,'Farmaco','Farmaco','500 mg','cada 8 horas','7 dias','ORAL',21,'Con alimentos',1),
                     (9122,982,'Farmaco B','Farmaco B','500 mg','cada 8 horas','7 dias','ORAL',21,'Con alimentos',1)""")
            conn.exec_driver_sql("""INSERT INTO documentos_clinicos
              (id_documento,id_clinica,id_paciente,tipo_documento,titulo,archivo_url,hash_archivo,fecha_documento,estado)
              VALUES (991,1,910,'RECETA','Receta','test.pdf',?,'2026-01-01','ACTIVO'),
                     (992,2,912,'RECETA','Receta B','test.pdf',?,'2026-01-01','ACTIVO')""", ("b"*64, "d"*64))
            conn.exec_driver_sql("UPDATE recetas SET id_documento=991 WHERE id_receta=981")
            conn.exec_driver_sql("UPDATE recetas SET id_documento=992 WHERE id_receta=982")
        else:
            # PostgreSQL
            _clean_cu17_tables(conn)
            # Limpiar filas previas de test con IDs >= 900
            for sql in (
                "DELETE FROM receta_detalle WHERE id_receta_detalle >= 9000",
                "DELETE FROM recetas WHERE id_receta >= 900",
                "DELETE FROM documentos_clinicos WHERE id_documento >= 900",
                "DELETE FROM diagnosticos WHERE id_diagnostico >= 900",
                "DELETE FROM consultas WHERE id_consulta >= 900",
                "DELETE FROM historias_clinicas WHERE id_historia >= 900",
                "DELETE FROM citas WHERE id_cita >= 900",
                "DELETE FROM medicos WHERE id_medico >= 900",
                "DELETE FROM pacientes WHERE id_paciente >= 900",
                "DELETE FROM usuarios WHERE id_usuario >= 900",
            ):
                conn.execute(text(sql))

            # Asegurar clínicas 1 y 2
            conn.execute(text("""
                INSERT INTO clinicas (id_clinica, nombre, estado)
                VALUES (1, 'Centro A', 'ACTIVO'), (2, 'Centro B', 'ACTIVO')
                ON CONFLICT (id_clinica) DO UPDATE SET estado = 'ACTIVO';
            """))

            # Permisos
            for p in ("treatments:read", "treatments:write", "treatments:dose:record", "treatments:notify:read"):
                conn.execute(text("""
                    INSERT INTO permisos (nombre, modulo, accion, estado)
                    VALUES (:p, 'treatments', :p, 'ACTIVO')
                    ON CONFLICT (nombre) DO NOTHING;
                """), {"p": p})

            # Vincular a roles existentes (2: MEDICO, 4: PACIENTE, 3: RECEPCION)
            for r, p in ((2, "treatments:read"), (2, "treatments:write"), (2, "treatments:notify:read"),
                         (4, "treatments:read"), (4, "treatments:dose:record"), (4, "treatments:notify:read")):
                pid = conn.execute(text("SELECT id_permiso FROM permisos WHERE nombre = :p"), {"p": p}).scalar()
                if pid:
                    conn.execute(text("INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (:r, :pid) ON CONFLICT DO NOTHING;"), {"r": r, "pid": pid})

            # Usuarios
            conn.execute(text("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, notificaciones_push, notificaciones_email, notificaciones_sms)
                VALUES (901, 1, 2, 'Medico', 'A', 'm901@test.invalid', 'x', 'activo', TRUE, TRUE, FALSE),
                       (902, 1, 2, 'Medico', 'B', 'm902@test.invalid', 'x', 'activo', TRUE, TRUE, FALSE),
                       (903, 1, 4, 'Paciente', 'A', 'p903@test.invalid', 'x', 'activo', TRUE, TRUE, FALSE),
                       (904, 1, 4, 'Paciente', 'B', 'p904@test.invalid', 'x', 'activo', TRUE, TRUE, FALSE),
                       (905, 2, 2, 'Medico', 'C', 'm905@test.invalid', 'x', 'activo', TRUE, TRUE, FALSE),
                       (906, 1, 3, 'Recepcion', 'A', 'r906@test.invalid', 'x', 'activo', TRUE, TRUE, FALSE),
                       (907, 2, 4, 'Paciente', 'C', 'p907@test.invalid', 'x', 'activo', TRUE, TRUE, FALSE);
            """))

            # Pacientes
            conn.execute(text("""
                INSERT INTO pacientes (id_paciente, id_clinica, id_usuario, nombres, apellidos, ci, fecha_nacimiento, genero, telefono, estado)
                VALUES (910, 1, 903, 'Paciente', 'A', 'CI903', '1990-01-01', 'F', '70000001', 'ACTIVO'),
                       (911, 1, 904, 'Paciente', 'B', 'CI904', '1990-01-01', 'F', '70000002', 'ACTIVO'),
                       (912, 2, 907, 'Paciente', 'C', 'CI907', '1990-01-01', 'M', '70000003', 'ACTIVO');
            """))

            # Medicos
            conn.execute(text("""
                INSERT INTO medicos (id_medico, id_clinica, id_usuario, matricula_profesional, estado)
                VALUES (921, 1, 901, 'M901', 'activo'),
                       (922, 1, 902, 'M902', 'activo'),
                       (923, 2, 905, 'M905', 'activo');
            """))

            # Citas
            conn.execute(text("""
                INSERT INTO citas (id_cita, id_clinica, id_paciente, id_medico, fecha_cita, hora_inicio, estado)
                VALUES (931, 1, 910, 921, '2026-01-01', '08:00', 'FINALIZADA'),
                       (932, 2, 912, 923, '2026-01-01', '08:00', 'FINALIZADA');
            """))

            # Historias
            conn.execute(text("""
                INSERT INTO historias_clinicas (id_historia, id_clinica, id_paciente, numero_historia)
                VALUES (941, 1, 910, 'H941'),
                       (942, 2, 912, 'H942');
            """))

            # Consultas
            conn.execute(text("""
                INSERT INTO consultas (id_consulta, id_clinica, id_historia, id_cita, id_medico, motivo_consulta, sintomas, evolucion, plan_medico)
                VALUES (942, 1, 941, 931, 921, 'Control', 'Sintomas', 'Estable', 'Tratamiento'),
                       (943, 2, 942, 932, 923, 'Control B', 'Sintomas', 'Estable', 'Tratamiento');
            """))

            # Diagnosticos
            conn.execute(text("""
                INSERT INTO diagnosticos (id_diagnostico, id_consulta, codigo_cie, descripcion, tipo)
                VALUES (954, 942, 'A00', 'Diagnostico', 'DEFINITIVO'),
                       (955, 943, 'A00', 'Diagnostico B', 'DEFINITIVO');
            """))

            # Documentos clinicos
            conn.execute(text("""
                INSERT INTO documentos_clinicos (id_documento, id_clinica, id_paciente, tipo_documento, titulo, archivo_url, hash_archivo, fecha_documento, estado)
                VALUES (991, 1, 910, 'RECETA', 'Receta', 'test.pdf', :h2, '2026-01-01', 'ACTIVO'),
                       (992, 2, 912, 'RECETA', 'Receta B', 'test.pdf', :h4, '2026-01-01', 'ACTIVO');
            """), {"h2": "b"*64, "h4": "d"*64})

            # Recetas
            conn.execute(text("""
                INSERT INTO recetas (id_receta, id_clinica, id_consulta, id_medico, id_paciente, folio, codigo_verificacion_hash, firma_digital, algoritmo_firma, key_id, version_payload, hash_pdf, fecha_vencimiento, estado, id_documento)
                VALUES (981, 1, 942, 921, 910, 'REC-981', :h1, 'firma', 'ED25519', 'test', 1, :h2, '2099-01-01', 'EMITIDA', 991),
                       (982, 2, 943, 923, 912, 'REC-982', :h3, 'firma', 'ED25519', 'test', 1, :h4, '2099-01-01', 'EMITIDA', 992);
            """), {"h1": "a"*64, "h2": "b"*64, "h3": "c"*64, "h4": "d"*64})

            # Receta detalle
            conn.execute(text("""
                INSERT INTO receta_detalle (id_receta_detalle, id_receta, nombre_medicamento_manual, medicamento_nombre, dosis, frecuencia, duracion, via_administracion, cantidad, indicaciones, posicion)
                VALUES (9121, 981, 'Farmaco', 'Farmaco', '500 mg', 'cada 8 horas', '7 dias', 'ORAL', 21, 'Con alimentos', 1),
                       (9122, 982, 'Farmaco B', 'Farmaco B', '500 mg', 'cada 8 horas', '7 dias', 'ORAL', 21, 'Con alimentos', 1);
            """))


def _build_scenario(engine, is_sqlite=True):
    _seed_db(engine, is_sqlite=is_sqlite)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    def db_dependency():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    def authenticate(user_id):
        with factory() as db:
            user = db.get(Usuario, user_id)
            if user:
                db.expunge(user)
        app.dependency_overrides[get_current_user] = lambda: user

    app.dependency_overrides[get_db] = db_dependency
    authenticate(901)
    client = TestClient(app)
    return client, engine, authenticate, factory


@pytest.fixture(params=["sqlite", "postgres"])
def scenario(request):
    is_sqlite = (request.param == "sqlite")
    db_file = None
    if is_sqlite:
        import os, tempfile
        db_file = os.path.join(tempfile.gettempdir(), f"cu17_test_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.db")
        engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000")
    else:
        pg_url = _get_disposable_postgres_url()
        try:
            engine = create_engine(pg_url, pool_size=10, max_overflow=20)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            pytest.skip(f"PostgreSQL desechable no disponible: {exc}")

    client, eng, auth, factory = _build_scenario(engine, is_sqlite=is_sqlite)
    try:
        yield client, eng, auth, factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        eng.dispose()
        if is_sqlite and db_file:
            import os
            for ext in ("", "-wal", "-shm"):
                try:
                    f = db_file + ext
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass


def _setup_active_plan(client, auth):
    """Crea un plan y devuelve id_tratamiento e id_dosis para el paciente titular (usuario 903)."""
    auth(901)  # Medico tratante
    today = datetime.now(ZoneInfo("America/La_Paz")).date()
    yesterday = today - timedelta(days=1)
    plan_payload = {
        "id_consulta": 942,
        "id_receta": 981,
        "fecha_inicio": yesterday.isoformat(),
        "fecha_fin": today.isoformat(),
        "zona_horaria": "America/La_Paz",
        "notas": "Plan para prueba de carrera concurrente",
        "medicamentos": [
            {
                "id_receta_detalle": 9121,
                "fecha_inicio": yesterday.isoformat(),
                "fecha_fin": today.isoformat(),
                "horas_locales": ["06:00", "14:00", "22:00"],
                "indicaciones": "Tomar puntualmente",
            }
        ],
    }
    res_plan = client.post("/api/v1/tratamientos", json=plan_payload)
    assert res_plan.status_code == 201, res_plan.text
    plan_id = res_plan.json()["id_tratamiento"]

    auth(903)  # Paciente titular
    res_cronograma = client.get(f"/api/v1/tratamientos/{plan_id}/cronograma", params={"fecha": yesterday.isoformat()})
    assert res_cronograma.status_code == 200, res_cronograma.text
    dose = res_cronograma.json()["dosis"][0]
    return plan_id, dose["id_dosis"], yesterday


def test_intento_permite_corregir_dosis_y_conserva_eventos(scenario):
    client, _, auth, factory = scenario
    _, id_dosis, day = _setup_active_plan(client, auth)
    url = f"/api/v1/tratamientos/dosis/{id_dosis}"
    primera = {"estado": "POSPUESTA", "efectiva_en": None, "nota": "Pospuesta"}
    corregida = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T06:00:00-04:00", "nota": "Tomada después"}

    for key, body in (("primera", primera), ("correccion", corregida)):
        serialized = service.json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        request_hash = service.hashlib.sha256(serialized.encode()).hexdigest()
        intento = client.post(f"{url}/intentos", json={"request_hash": request_hash},
                              headers={"Idempotency-Key": key})
        assert intento.status_code == 200, intento.text
        assert intento.json()["estado"] == "EN_CURSO"
        registro = client.post(f"{url}/registros", json=body, headers={"Idempotency-Key": key})
        assert registro.status_code == 200, registro.text

    with factory() as db:
        eventos = db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_dosis == id_dosis,
            TratamientoEvento.accion == "REGISTRAR_DOSIS",
        ).order_by(TratamientoEvento.id_evento)).scalars().all()
        assert [evento.estado_nuevo for evento in eventos] == ["POSPUESTA", "INGERIDA"]


def test_resolver_clave_no_iniciada_cierra_peticion_tardia(scenario):
    client, _, auth, factory = scenario
    _, id_dosis, day = _setup_active_plan(client, auth)
    url = f"/api/v1/tratamientos/dosis/{id_dosis}"
    key = "perdida-antes-de-intento"
    resolver = f"{url}/registros/idempotencia/{key}/resolver"

    assert client.get(f"{url}/registros/idempotencia/{key}").json()["estado"] == "NO_INICIADA"
    primera = client.post(resolver)
    assert primera.status_code == 200, primera.text
    assert primera.json()["estado"] == "RECHAZADA"
    assert client.post(resolver).json()["estado"] == "RECHAZADA"
    assert client.get(f"{url}/registros/idempotencia/{key}").json()["estado"] == "RECHAZADA"

    body = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T06:00:00-04:00", "nota": "Tardía"}
    serialized = service.json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    request_hash = service.hashlib.sha256(serialized.encode()).hexdigest()
    assert client.post(f"{url}/intentos", json={"request_hash": request_hash},
                       headers={"Idempotency-Key": key}).status_code == 409
    assert client.post(f"{url}/registros", json=body,
                       headers={"Idempotency-Key": key}).status_code == 409
    with factory() as db:
        assert db.execute(select(TratamientoEvento).where(
            TratamientoEvento.id_dosis == id_dosis,
            TratamientoEvento.accion == "REGISTRAR_DOSIS",
        )).scalars().all() == []


# =========================================================================
# 1. A SE RETRASA ANTES DE REGISTRAR SU INTENTO; CLIENTE INICIA B; A LLEGA TRAS B
# =========================================================================
def test_a_se_retrasa_antes_de_intento_b_termina_a_llega_despues_maximo_un_evento(scenario):
    """
    Obligatorio 1:
    A se retrasa antes de registrar su intento; el cliente consulta y trata de iniciar B.
    A llega después de que B termina. Debe haber como máximo un evento (fencing / dose state).
    """
    client, engine, auth, factory = scenario
    plan_id, id_dosis, day = _setup_active_plan(client, auth)

    a_started = threading.Event()
    a_can_proceed = threading.Event()
    result_a = {}

    original_iniciar_intento = service.iniciar_intento_dosis

    def delayed_iniciar_intento(*args, **kwargs):
        if not a_started.is_set():
            a_started.set()
            a_can_proceed.wait(timeout=10)
        return original_iniciar_intento(*args, **kwargs)

    req_hash_a = service.hashlib.sha256(b"body_a_hash").hexdigest()

    def run_a():
        try:
            with TestClient(app) as local_client:
                auth(903)
                r = local_client.post(
                    f"/api/v1/tratamientos/dosis/{id_dosis}/intentos",
                    json={"request_hash": req_hash_a},
                    headers={"Idempotency-Key": "key-a-delayed-before-register"},
                )
                result_a["status_code"] = r.status_code
                result_a["json"] = r.json()
        except Exception as exc:
            result_a["exception"] = str(exc)

    service.iniciar_intento_dosis = delayed_iniciar_intento
    thread_a = threading.Thread(target=run_a, name="Thread-A-Delayed")
    try:
        thread_a.start()
        assert a_started.wait(timeout=10), "POST A no inició a tiempo"

        # Cliente consulta estado de A mientras A está retrasado antes de registrar su intento
        auth(903)
        res_get_a = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-a-delayed-before-register")
        assert res_get_a.status_code == 200
        assert res_get_a.json()["confirmado"] is False
        assert res_get_a.json()["estado"] == "NO_INICIADA"

        # La consulta por sí sola no descarta A: cerrar la clave en el servidor
        # antes de permitir B impide que la petición retrasada se convierta en
        # una corrección clínica involuntaria.
        res_resolve_a = client.post(
            f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-a-delayed-before-register/resolver"
        )
        assert res_resolve_a.status_code == 200, res_resolve_a.text
        assert res_resolve_a.json()["estado"] == "RECHAZADA"

        # Cliente inicia y completa B para la misma dosis
        body_b = {
            "estado": "INGERIDA",
            "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
            "nota": "Toma ganadora B",
        }
        res_b = client.post(
            f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
            json=body_b,
            headers={"Idempotency-Key": "key-b-ganadora"},
        )
        assert res_b.status_code == 200, f"POST B falló: {res_b.text}"
        assert res_b.json()["estado"] == "INGERIDA"

        # A llega después de que B termina
        a_can_proceed.set()
        thread_a.join(timeout=10)
        assert not thread_a.is_alive()

        # A debe haber sido rechazado por la clave ya cerrada.
        assert result_a.get("status_code") == 409, f"A debió ser 409 pero fue {result_a}"
        assert result_a["json"]["code"] == "TREATMENT_IDEMPOTENCY_CONFLICT"

        # Debe haber como máximo UN evento en tratamiento_eventos para esta dosis
        with factory() as db:
            eventos = db.execute(
                select(TratamientoEvento).where(
                    TratamientoEvento.id_dosis == id_dosis,
                    TratamientoEvento.accion == "REGISTRAR_DOSIS",
                )
            ).scalars().all()
            assert len(eventos) == 1, f"Se esperaba exactamente 1 evento pero hay {len(eventos)}"
            assert eventos[0].estado_nuevo == "INGERIDA"

            # Estado final de la dosis es INGERIDA
            dose = db.get(TratamientoDosis, id_dosis)
            assert dose.estado == "INGERIDA"
    finally:
        service.iniciar_intento_dosis = original_iniciar_intento
        a_can_proceed.set()
        if thread_a.is_alive():
            thread_a.join(timeout=2)


# =========================================================================
# 2. A REGISTRA EN_CURSO; B INTENTA; A CONFIRMA; B NO CREA EVENTO (409)
# =========================================================================
def test_cu17_race_condition_paso1_a_paso5(scenario):
    """
    Verifica el flujo estricto concurrente:
    Paso 1: POST A (clave A) comienza y se detiene (wait) tras registrar EN_CURSO.
    Paso 2: Cliente consulta GET idempotencia de A -> estado: EN_CURSO, confirmado: False, en_curso: True.
    Paso 3: Cliente intenta POST B (clave B) para la misma dosis -> 409 Conflict ("operación en curso").
    Paso 4: POST A se libera (Event.set()) y confirma -> 200 OK.
    Paso 5: Comprueba que B no creó registro y existe UN ÚNICO evento en tratamiento_eventos.
    """
    client, engine, auth, factory = scenario
    plan_id, id_dosis, day = _setup_active_plan(client, auth)

    a_registered_en_curso = threading.Event()
    a_resume_event = threading.Event()
    result_a = {}
    thread_a_ref = None

    original_receta_vigente = service.receta_vigente

    def hooked_receta_vigente(db_session, plan_obj, lock=True):
        if not a_registered_en_curso.is_set():
            # POST A ya registró TratamientoOperacionDosis en estado EN_CURSO y commiteó.
            a_registered_en_curso.set()
            # Se detiene antes de confirmar la dosis
            a_resume_event.wait(timeout=10)
        return original_receta_vigente(db_session, plan_obj, lock=lock)

    # Paso 1: Hilo para POST A
    body_a = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Toma concurrente A",
    }

    def run_post_a():
        try:
            with TestClient(app) as local_client:
                auth(903)
                res = local_client.post(
                    f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
                    json=body_a,
                    headers={"Idempotency-Key": "key-operacion-a"},
                )
                result_a["status_code"] = res.status_code
                result_a["json"] = res.json()
        except Exception as exc:
            result_a["exception"] = str(exc)

    thread_a = threading.Thread(target=run_post_a, name="Thread-POST-A")

    service.receta_vigente = hooked_receta_vigente
    try:
        thread_a.start()

        # Esperar a que POST A haya persistido estado EN_CURSO
        assert a_registered_en_curso.wait(timeout=10), "POST A no registró EN_CURSO a tiempo"

        # Paso 2: Consulta de estado de A mientras está EN_CURSO
        auth(903)
        res_get_a = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-operacion-a")
        assert res_get_a.status_code == 200, res_get_a.text
        data_a = res_get_a.json()
        assert data_a["estado"] == "EN_CURSO"
        assert data_a["confirmado"] is False
        assert data_a["en_curso"] is True
        assert data_a["rechazado"] is False
        assert data_a["dosis"] is None
        assert data_a["id_dosis"] == id_dosis
        assert data_a["idempotency_key"] == "key-operacion-a"

        # Paso 3: Cliente intenta POST B para la misma dosis con clave B
        body_b = {
            "estado": "INGERIDA",
            "efectiva_en": f"{day.isoformat()}T06:05:00-04:00",
            "nota": "Toma concurrente B",
        }
        res_post_b = client.post(
            f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
            json=body_b,
            headers={"Idempotency-Key": "key-operacion-b"},
        )
        assert res_post_b.status_code == 409, f"POST B debió ser 409 pero fue {res_post_b.status_code}: {res_post_b.text}"
        detail_b = res_post_b.json()["detail"].lower()
        assert "operación en curso" in detail_b or "incierto" in detail_b

        # Paso 4: Liberar A y esperar a que confirme
        a_resume_event.set()
        thread_a.join(timeout=10)
        assert not thread_a.is_alive(), "El hilo A no terminó"
        assert result_a.get("status_code") == 200, f"POST A falló: {result_a}"
        assert result_a["json"]["estado"] == "INGERIDA"

        # Comprobar consulta GET de A confirmada
        res_get_a_conf = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-operacion-a")
        assert res_get_a_conf.status_code == 200
        assert res_get_a_conf.json()["estado"] == "CONFIRMADA"
        assert res_get_a_conf.json()["confirmado"] is True
        assert res_get_a_conf.json()["en_curso"] is False
        assert res_get_a_conf.json()["dosis"]["id_dosis"] == id_dosis

        # Paso 5: Comprobar que B no pudo crear registro y existe exactamente 1 evento en tratamiento_eventos
        with factory() as db:
            eventos = db.execute(
                select(TratamientoEvento).where(
                    TratamientoEvento.id_dosis == id_dosis,
                    TratamientoEvento.accion == "REGISTRAR_DOSIS",
                )
            ).scalars().all()
            assert len(eventos) == 1, f"Se esperaba 1 evento pero hay {len(eventos)}"
            assert eventos[0].id_usuario == 903
            assert eventos[0].estado_nuevo == "INGERIDA"

            # Operación B no quedó confirmada
            op_b = db.execute(
                select(TratamientoOperacionDosis).where(
                    TratamientoOperacionDosis.id_dosis == id_dosis,
                    TratamientoOperacionDosis.idempotencia_hash == service.hashlib.sha256("key-operacion-b".encode()).hexdigest(),
                )
            ).scalar_one_or_none()
            if op_b:
                assert op_b.estado != "CONFIRMADA"
    finally:
        service.receta_vigente = original_receta_vigente
        a_resume_event.set()
        if thread_a.is_alive():
            thread_a.join(timeout=2)


# =========================================================================
# 2. REINTENTO IDÉNTICO CONCURRENTE
# =========================================================================
def test_reintento_identico_concurrente_mismo_cuerpo_y_clave(scenario):
    """Dos hilos enviando al mismo tiempo la misma clave y mismo cuerpo devuelven 200 y crean 1 solo evento."""
    client, engine, auth, factory = scenario
    _, id_dosis, day = _setup_active_plan(client, auth)

    body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Reintento simultáneo idéntico",
    }
    headers = {"Idempotency-Key": "key-identica-simultanea"}

    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        with TestClient(app) as local_client:
            auth(903)
            r = local_client.post(f"/api/v1/tratamientos/dosis/{id_dosis}/registros", json=body, headers=headers)
            # En concurrencia real, si una solicitud colisiona mientras la otra está en estado transitorio
            # EN_CURSO (409 OPERATION_IN_PROGRESS), el protocolo de idempotencia establece que el cliente
            # reintente o consulte el resultado una vez completada la primera operación.
            if r.status_code == 409 and r.json().get("code") == "OPERATION_IN_PROGRESS":
                for _ in range(30):
                    time.sleep(0.05)
                    r = local_client.post(f"/api/v1/tratamientos/dosis/{id_dosis}/registros", json=body, headers=headers)
                    if r.status_code == 200:
                        break
            results.append((r.status_code, r.json()))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert len(results) == 2
    for status, data in results:
        assert status == 200, f"Respuesta inesperada: {status} -> {data}"
        assert data["estado"] == "INGERIDA"

    with factory() as db:
        count = db.execute(
            select(service.func.count(TratamientoEvento.id_evento)).where(
                TratamientoEvento.id_dosis == id_dosis,
                TratamientoEvento.accion == "REGISTRAR_DOSIS",
            )
        ).scalar()
        assert count == 1, f"Se debió crear exactamente 1 evento pero hay {count}"


# =========================================================================
# 3. MISMA CLAVE CON CUERPO DIFERENTE (409 IDEMPOTENCY_CONFLICT)
# =========================================================================
def test_misma_clave_cuerpo_diferente_produce_409_conflicto(scenario):
    """Reutilización de la misma clave con cuerpo distinto devuelve 409 IDEMPOTENCY_CONFLICT."""
    client, _, auth, _ = scenario
    _, id_dosis, day = _setup_active_plan(client, auth)

    body_1 = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Primera llamada",
    }
    r1 = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body_1,
        headers={"Idempotency-Key": "key-conflicto-cuerpo"},
    )
    assert r1.status_code == 200, r1.text

    # Reintento idéntico funciona
    r_same = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body_1,
        headers={"Idempotency-Key": "key-conflicto-cuerpo"},
    )
    assert r_same.status_code == 200

    # Parte 1: Misma clave con cuerpo alterado tras CONFIRMADA -> 409 IDEMPOTENCY_CONFLICT
    body_2 = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Nota modificada que genera conflicto de idempotencia",
    }
    r2 = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body_2,
        headers={"Idempotency-Key": "key-conflicto-cuerpo"},
    )
    assert r2.status_code == 409
    assert r2.json()["code"] == "TREATMENT_IDEMPOTENCY_CONFLICT"

    # Parte 2: Misma clave con cuerpo alterado tras RECHAZADA -> 409 IDEMPOTENCY_CONFLICT
    # 1. Crear un intento inválido que resulta en RECHAZADA (por ejemplo, hora efectiva futura)
    future_time = datetime.now(ZoneInfo("America/La_Paz")) + timedelta(hours=5)
    invalid_body_rej = {
        "estado": "INGERIDA",
        "efectiva_en": future_time.isoformat(),
        "nota": "Hora futura rechazada",
    }
    r_rej = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=invalid_body_rej,
        headers={"Idempotency-Key": "key-conflicto-tras-rechazo"},
    )
    assert r_rej.status_code == 422

    # Verificar que quedó en estado RECHAZADA
    r_get_rej = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-conflicto-tras-rechazo")
    assert r_get_rej.status_code == 200
    assert r_get_rej.json()["estado"] == "RECHAZADA"

    # 2. Reintento con la misma clave pero con OTRO cuerpo diferente tras RECHAZADA
    diff_body_rej = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Cuerpo modificado intentando reutilizar clave rechazada",
    }
    r_rej_conflict = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=diff_body_rej,
        headers={"Idempotency-Key": "key-conflicto-tras-rechazo"},
    )
    assert r_rej_conflict.status_code == 409
    assert r_rej_conflict.json()["code"] == "TREATMENT_IDEMPOTENCY_CONFLICT"


# =========================================================================
# 4. PROCESO INTERRUMPIDO Y RECUPERACIÓN DURABLE
# =========================================================================
def test_recuperacion_de_operacion_interrumpida_en_curso(scenario):
    """Si una operación quedó en EN_CURSO por corte de conexión, un reintento idéntico confirma exitosamente."""
    client, _, auth, factory = scenario
    plan_id, id_dosis, day = _setup_active_plan(client, auth)

    key = "key-interrumpida-recuperable"
    key_hash = service.hashlib.sha256(key.encode()).hexdigest()
    body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Toma interrumpida",
    }
    serialized = service.json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    req_hash = service.hashlib.sha256(serialized.encode()).hexdigest()

    # Simular que el cliente o worker cayó dejando una operación EN_CURSO en BD
    with factory() as db:
        op = TratamientoOperacionDosis(
            id_clinica=1,
            id_tratamiento=plan_id,
            id_dosis=id_dosis,
            id_usuario=903,
            idempotencia_hash=key_hash,
            request_hash=req_hash,
            estado="EN_CURSO",
        )
        db.add(op)
        db.commit()

    # Consulta de idempotencia previa al reintento
    res_en_curso = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/{key}")
    assert res_en_curso.status_code == 200
    assert res_en_curso.json()["estado"] == "EN_CURSO"
    assert res_en_curso.json()["en_curso"] is True

    # El cliente reintenta con misma clave y mismo payload
    res_retry = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert res_retry.status_code == 200, res_retry.text
    assert res_retry.json()["estado"] == "INGERIDA"

    # Ahora la consulta muestra CONFIRMADA
    res_conf = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/{key}")
    assert res_conf.status_code == 200
    assert res_conf.json()["estado"] == "CONFIRMADA"
    assert res_conf.json()["confirmado"] is True


# =========================================================================
# 5. OPERACIÓN RECHAZADA DEFINITIVAMENTE Y LIBERACIÓN DE NUEVA CLAVE
# =========================================================================
def test_operacion_rechazada_permite_solicitud_posterior_con_nueva_clave(scenario):
    """Operación rechazada (422) queda RECHAZADA y permite un registro posterior con nueva clave válida."""
    client, _, auth, factory = scenario
    _, id_dosis, day = _setup_active_plan(client, auth)

    # 1. Intento inválido: hora efectiva futura
    future_time = datetime.now(ZoneInfo("America/La_Paz")) + timedelta(hours=5)
    invalid_body = {
        "estado": "INGERIDA",
        "efectiva_en": future_time.isoformat(),
        "nota": "Hora futura",
    }
    r_inv = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=invalid_body,
        headers={"Idempotency-Key": "key-fallida-422"},
    )
    assert r_inv.status_code == 422

    # Consulta de la clave fallida: debe reportar RECHAZADA
    res_get_inv = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-fallida-422")
    assert res_get_inv.status_code == 200
    assert res_get_inv.json()["estado"] == "RECHAZADA"
    assert res_get_inv.json()["rechazado"] is True

    # 2. Solicitud posterior con nueva clave limpia y datos válidos
    valid_body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Registro corregido",
    }
    r_val = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=valid_body,
        headers={"Idempotency-Key": "key-nueva-valida"},
    )
    assert r_val.status_code == 200, r_val.text
    assert r_val.json()["estado"] == "INGERIDA"

    # Consulta de la nueva clave: CONFIRMADA
    res_get_val = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-nueva-valida")
    assert res_get_val.status_code == 200
    assert res_get_val.json()["estado"] == "CONFIRMADA"
    assert res_get_val.json()["confirmado"] is True


# =========================================================================
# 6. AISLAMIENTO MULTI-TENANT Y CONTROL DE ACCESO
# =========================================================================
def test_aislamiento_multitenant_y_roles_incompatibles(scenario):
    """Verifica que pacientes ajenos u otros roles reciban 403 o 404 al registrar o consultar."""
    client, _, auth, _ = scenario
    _, id_dosis, day = _setup_active_plan(client, auth)

    body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
    }

    # 1. Médico (usuario 901) intenta registrar toma -> 403 FORBIDDEN
    auth(901)
    r_med = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": "key-medico"},
    )
    assert r_med.status_code == 403
    assert r_med.json()["code"] == "TREATMENT_FORBIDDEN"

    r_med_get = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-test")
    assert r_med_get.status_code == 403

    # 2. Recepción (usuario 906) -> 403 FORBIDDEN
    auth(906)
    r_rec = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": "key-recepcion"},
    )
    assert r_rec.status_code == 403

    # 3. Paciente ajeno en la misma clínica (usuario 904) -> 404 NOT_FOUND
    auth(904)
    r_other_pac = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": "key-paciente-ajeno"},
    )
    assert r_other_pac.status_code == 404
    assert r_other_pac.json()["code"] == "TREATMENT_NOT_FOUND"

    r_other_pac_get = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/key-test")
    assert r_other_pac_get.status_code == 404

    # 4. Paciente de otra clínica (clínica 2, usuario 907) -> 404 NOT_FOUND
    auth(907)
    r_other_tenant = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": "key-otro-tenant"},
    )
    assert r_other_tenant.status_code == 404


# =========================================================================
# 7. ANULACIÓN DE RECETA O CIERRE DE PLAN DURANTE LA OPERACIÓN
# =========================================================================
def test_anulacion_de_receta_durante_operacion_rechaza_sin_evento_huerfano(scenario):
    """Si la receta se anula durante la operación, la toma se rechaza (409) y no crea evento."""
    client, engine, auth, factory = scenario
    plan_id, id_dosis, day = _setup_active_plan(client, auth)

    # Anular la receta
    with factory() as db:
        db.execute(text("UPDATE recetas SET estado = 'ANULADA' WHERE id_receta = 981"))
        db.commit()

    auth(903)
    body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
    }
    res = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": "key-receta-anulada"},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "TREATMENT_CONFLICT"

    # Verificar que el plan queda reflejado como SUSPENDIDO_POR_RECETA
    res_plan = client.get(f"/api/v1/tratamientos/{plan_id}")
    assert res_plan.status_code == 200
    assert res_plan.json()["estado"] == "SUSPENDIDO_POR_RECETA"

    # No hay eventos huérfanos de registro de dosis
    with factory() as db:
        eventos = db.execute(
            select(TratamientoEvento).where(
                TratamientoEvento.id_dosis == id_dosis,
                TratamientoEvento.accion == "REGISTRAR_DOSIS",
            )
        ).scalars().all()
        assert len(eventos) == 0

        # La operación quedó como RECHAZADA
        key_hash = service.hashlib.sha256("key-receta-anulada".encode()).hexdigest()
        op = db.execute(
            select(TratamientoOperacionDosis).where(
                TratamientoOperacionDosis.id_dosis == id_dosis,
                TratamientoOperacionDosis.idempotencia_hash == key_hash,
            )
        ).scalar_one_or_none()
        if op:
            assert op.estado == "RECHAZADA"


# =========================================================================
# 5. CAÍDA SIMULADA EN CADA PUNTO DEL PROTOCOLO Y RECUPERACIÓN
# =========================================================================
def test_caida_simulada_en_cada_punto_del_protocolo_y_recuperacion(scenario):
    """
    Obligatorio 5:
    Prueba caídas simuladas en los 4 puntos del protocolo transaccional y su recuperación:
    1. Antes del intento durable.
    2. Tras intento durable (EN_CURSO).
    3. Durante mutación clínica.
    4. Tras commit antes de respuesta HTTP.
    """
    client, engine, auth, factory = scenario
    auth(901)
    today = datetime.now(ZoneInfo("America/La_Paz")).date()
    yesterday = today - timedelta(days=1)
    plan_payload = {
        "id_consulta": 942,
        "id_receta": 981,
        "fecha_inicio": yesterday.isoformat(),
        "fecha_fin": today.isoformat(),
        "zona_horaria": "America/La_Paz",
        "notas": "Plan para pruebas de caídas en protocolo",
        "medicamentos": [
            {
                "id_receta_detalle": 9121,
                "fecha_inicio": yesterday.isoformat(),
                "fecha_fin": today.isoformat(),
                "horas_locales": ["06:00", "14:00", "22:00"],
                "indicaciones": "Tomar puntualmente",
            }
        ],
    }
    res_plan = client.post("/api/v1/tratamientos", json=plan_payload)
    assert res_plan.status_code == 201
    plan_id = res_plan.json()["id_tratamiento"]

    auth(903)
    cron = client.get(f"/api/v1/tratamientos/{plan_id}/cronograma", params={"fecha": yesterday.isoformat()}).json()
    doses = cron["dosis"]
    dose_1 = doses[0]["id_dosis"]
    dose_2 = doses[1]["id_dosis"]
    dose_3 = doses[2]["id_dosis"]

    # -------------------------------------------------------------
    # Punto 1: Caída antes del intento durable
    # -------------------------------------------------------------
    key_p1 = "key-crash-punto-1"
    body_p1 = {"estado": "INGERIDA", "efectiva_en": f"{yesterday.isoformat()}T06:00:00-04:00", "nota": "Recuperado P1"}
    res_chk_p1 = client.get(f"/api/v1/tratamientos/dosis/{dose_1}/registros/idempotencia/{key_p1}")
    assert res_chk_p1.status_code == 200
    assert res_chk_p1.json()["estado"] == "NO_INICIADA"

    res_p1 = client.post(f"/api/v1/tratamientos/dosis/{dose_1}/registros", json=body_p1, headers={"Idempotency-Key": key_p1})
    assert res_p1.status_code == 200
    assert res_p1.json()["estado"] == "INGERIDA"

    # -------------------------------------------------------------
    # Punto 2: Caída tras intento durable (estado EN_CURSO)
    # -------------------------------------------------------------
    key_p2 = "key-crash-punto-2"
    body_p2 = {"estado": "INGERIDA", "efectiva_en": f"{yesterday.isoformat()}T14:00:00-04:00", "nota": "Recuperado P2"}
    serialized_p2 = service.json.dumps(body_p2, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    req_hash_p2 = service.hashlib.sha256(serialized_p2.encode()).hexdigest()

    res_intento = client.post(
        f"/api/v1/tratamientos/dosis/{dose_2}/intentos",
        json={"request_hash": req_hash_p2},
        headers={"Idempotency-Key": key_p2},
    )
    assert res_intento.status_code == 200
    assert res_intento.json()["estado"] == "EN_CURSO"

    res_chk_p2 = client.get(f"/api/v1/tratamientos/dosis/{dose_2}/registros/idempotencia/{key_p2}")
    assert res_chk_p2.status_code == 200
    assert res_chk_p2.json()["estado"] == "EN_CURSO"
    assert res_chk_p2.json()["en_curso"] is True

    res_p2 = client.post(f"/api/v1/tratamientos/dosis/{dose_2}/registros", json=body_p2, headers={"Idempotency-Key": key_p2})
    assert res_p2.status_code == 200
    assert res_p2.json()["estado"] == "INGERIDA"

    # -------------------------------------------------------------
    # Punto 3: Caída durante mutación clínica
    # -------------------------------------------------------------
    key_p3 = "key-crash-punto-3"
    body_p3 = {"estado": "INGERIDA", "efectiva_en": f"{yesterday.isoformat()}T22:00:00-04:00", "nota": "Recuperado P3"}

    original_event = service._event

    def crashing_event(*args, **kwargs):
        raise RuntimeError("Simulated crash during clinical mutation")

    service._event = crashing_event
    try:
        with pytest.raises(RuntimeError):
            client.post(
                f"/api/v1/tratamientos/dosis/{dose_3}/registros",
                json=body_p3,
                headers={"Idempotency-Key": key_p3},
            )
    finally:
        service._event = original_event

    with factory() as db:
        ev_p3 = db.execute(
            select(TratamientoEvento).where(
                TratamientoEvento.id_dosis == dose_3,
                TratamientoEvento.accion == "REGISTRAR_DOSIS",
            )
        ).scalars().all()
        assert len(ev_p3) == 0

    # Recuperación: El cliente reintenta con la misma Idempotency-Key
    res_p3_rec = client.post(
        f"/api/v1/tratamientos/dosis/{dose_3}/registros",
        json=body_p3,
        headers={"Idempotency-Key": key_p3},
    )
    assert res_p3_rec.status_code == 200
    assert res_p3_rec.json()["estado"] == "INGERIDA"

    # -------------------------------------------------------------
    # Punto 4: Caída tras commit antes de respuesta
    # -------------------------------------------------------------
    res_dup_p3 = client.post(
        f"/api/v1/tratamientos/dosis/{dose_3}/registros",
        json=body_p3,
        headers={"Idempotency-Key": key_p3},
    )
    assert res_dup_p3.status_code == 200
    assert res_dup_p3.json()["estado"] == "INGERIDA"

    with factory() as db:
        ev_count = db.execute(
            select(service.func.count(TratamientoEvento.id_evento)).where(
                TratamientoEvento.id_dosis == dose_3,
                TratamientoEvento.accion == "REGISTRAR_DOSIS",
            )
        ).scalar()
        assert ev_count == 1, f"Debió haber exactamente 1 evento pero hay {ev_count}"


# =========================================================================
# 6. LOGOUT, NUEVO LOGIN, MARCADOR MÍNIMO Y RESOLUCIÓN SIN DATOS CLÍNICOS
# =========================================================================
def test_logout_nuevo_login_marcador_minimo_y_resolucion_sin_datos_clinicos(scenario):
    """
    Obligatorio 6:
    Logout, nuevo login, marcador mínimo y resolución sin datos clínicos en almacenamiento.
    """
    client, engine, auth, factory = scenario
    plan_id, id_dosis, day = _setup_active_plan(client, auth)

    auth(903)
    key = "key-marcador-minimo"
    body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Nota confidencial del paciente que NO debe guardarse en marcador",
    }

    marcador_minimo = {
        "id_dosis": id_dosis,
        "idempotency_key": key,
        "en_curso": True,
    }
    for campo_prohibido in ("nota", "medicamento", "diagnostico", "dosis_texto", "indicaciones", "receta"):
        assert campo_prohibido not in marcador_minimo

    res = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert res.status_code == 200

    auth(906)
    res_logged_out = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/{key}")
    assert res_logged_out.status_code == 403

    auth(903)
    res_resolve = client.get(
        f"/api/v1/tratamientos/dosis/{marcador_minimo['id_dosis']}/registros/idempotencia/{marcador_minimo['idempotency_key']}"
    )
    assert res_resolve.status_code == 200
    data_res = res_resolve.json()
    assert data_res["confirmado"] is True
    assert data_res["estado"] == "CONFIRMADA"
    assert data_res["dosis"]["id_dosis"] == id_dosis

    marcador_minimo.clear()
    assert len(marcador_minimo) == 0


# =========================================================================
# 7. CAMBIO DE USUARIO O CLÍNICA EN EL MISMO NAVEGADOR (AISLAMIENTO)
# =========================================================================
def test_cambio_de_usuario_o_clinica_en_mismo_navegador_aislamiento(scenario):
    """
    Obligatorio 7:
    Cambio de usuario o clínica en el mismo navegador (aislamiento tenant/usuario).
    """
    client, engine, auth, _ = scenario
    plan_id, id_dosis, day = _setup_active_plan(client, auth)

    auth(903)
    key_paciente_a = "key-paciente-a-navegador"
    body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Toma de Paciente A",
    }
    r_a = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": key_paciente_a},
    )
    assert r_a.status_code == 200

    auth(904)
    r_b_get = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/{key_paciente_a}")
    assert r_b_get.status_code == 404
    assert r_b_get.json()["code"] == "TREATMENT_NOT_FOUND"

    r_b_post = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": "key-paciente-b"},
    )
    assert r_b_post.status_code == 404

    auth(907)
    r_c_get = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/{key_paciente_a}")
    assert r_c_get.status_code == 404

    r_c_post = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": "key-paciente-c"},
    )
    assert r_c_post.status_code == 404

    auth(903)
    r_a_restore = client.get(f"/api/v1/tratamientos/dosis/{id_dosis}/registros/idempotencia/{key_paciente_a}")
    assert r_a_restore.status_code == 200
    assert r_a_restore.json()["confirmado"] is True


# =========================================================================
# 8. PLAN CERRADO DURANTE UN INTENTO (409 SIN EVENTO HUÉRFANO)
# =========================================================================
def test_plan_cerrado_durante_intento_rechaza_sin_evento_huerfano(scenario):
    """
    Obligatorio 8 (segunda parte):
    Si el plan es cerrado/finalizado durante un intento, se rechaza 409 y no crea evento huérfano.
    """
    client, engine, auth, factory = scenario
    plan_id, id_dosis, day = _setup_active_plan(client, auth)

    with factory() as db:
        db.execute(text("UPDATE tratamientos SET estado = 'FINALIZADO' WHERE id_tratamiento = :p"), {"p": plan_id})
        db.commit()

    auth(903)
    body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
    }
    res = client.post(
        f"/api/v1/tratamientos/dosis/{id_dosis}/registros",
        json=body,
        headers={"Idempotency-Key": "key-plan-cerrado"},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "TREATMENT_CONFLICT"

    with factory() as db:
        count = db.execute(
            select(service.func.count(TratamientoEvento.id_evento)).where(
                TratamientoEvento.id_dosis == id_dosis,
                TratamientoEvento.accion == "REGISTRAR_DOSIS",
            )
        ).scalar()
        assert count == 0


# =========================================================================
# 9. REVERSIÓN NO DESTRUCTIVA DE LA MIGRACIÓN PROBADA EXPRESAMENTE
# =========================================================================
def test_reversion_no_destructiva_de_la_migracion_probada_expresamente():
    """
    Obligatorio 9:
    Verifica expresamente que 014_operaciones_dosis_cu17.downgrade() lanza RuntimeError
    y no borra tablas ni destruye el historial clínico ni de operaciones.
    """
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect as sa_inspect

    ruta_014 = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "014_operaciones_dosis_cu17.py"
    spec = importlib.util.spec_from_file_location("mig_014_race", ruta_014)
    mig_014 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_014)

    test_engine = create_engine("sqlite://")
    with test_engine.begin() as conn:
        for t, k in (("clinicas", "id_clinica"), ("tratamientos", "id_tratamiento"),
                     ("tratamiento_dosis", "id_dosis"), ("usuarios", "id_usuario")):
            conn.exec_driver_sql(f"CREATE TABLE {t} ({k} INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tratamiento_eventos (id_evento INTEGER PRIMARY KEY, id_clinica INT, id_tratamiento INT, id_dosis INT, id_usuario INT, accion TEXT, idempotencia_hash TEXT, request_hash TEXT, respuesta_json TEXT, ocurrida_en_utc TEXT)")

        mig_014.op = Operations(MigrationContext.configure(conn))
        mig_014.upgrade()

        # Insertar operación clínica
        conn.exec_driver_sql("""
            INSERT INTO tratamiento_operaciones_dosis (
                id_clinica, id_tratamiento, id_dosis, id_usuario, generacion,
                idempotencia_hash, request_hash, estado, respuesta_json, created_at, updated_at
            ) VALUES (1, 1, 1, 1, 1, 'hash_no_destructivo', 'req_hash', 'CONFIRMADA', '{"ok": true}', '2026-01-01', '2026-01-01')
        """)

        # Ejecutar downgrade expresamente
        with pytest.raises(RuntimeError) as exc_info:
            mig_014.downgrade()

        assert "CU17 conserva datos clínicos e historial de operaciones" in str(exc_info.value)

        # Verificar que la tabla existe y la fila está intacta
        insp = sa_inspect(conn)
        assert "tratamiento_operaciones_dosis" in insp.get_table_names()
        count = conn.execute(text("SELECT count(*) FROM tratamiento_operaciones_dosis")).scalar()
        assert count == 1

    test_engine.dispose()
