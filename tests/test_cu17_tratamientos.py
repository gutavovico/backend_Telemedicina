"""Escenarios de integración CU17, con datos aislados por clínica en SQLite."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


@pytest.fixture
def scenario():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    # El modelo compartido Auditoria usa BIGINT; SQLite solo autoincrementa INTEGER.
    # La tabla de la prueba reproduce el comportamiento de la secuencia PostgreSQL.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE auditoria")
        conn.exec_driver_sql("""CREATE TABLE auditoria (
            id_auditoria INTEGER PRIMARY KEY AUTOINCREMENT,
            id_clinica BIGINT NOT NULL, id_usuario BIGINT NOT NULL,
            tabla_afectada VARCHAR(150), registro_id BIGINT, accion VARCHAR(50) NOT NULL,
            descripcion VARCHAR, datos_anteriores JSON, datos_nuevos JSON,
            direccion_ip VARCHAR(45), fecha_hora DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )""")
        conn.exec_driver_sql("INSERT INTO clinicas (id_clinica,nombre,estado) VALUES (1,'Centro A','ACTIVO'),(2,'Centro B','ACTIVO')")
        conn.exec_driver_sql("INSERT INTO roles (id_rol,id_clinica,nombre,estado) VALUES (1,1,'MEDICO','ACTIVO'),(2,1,'PACIENTE','ACTIVO'),(3,1,'RECEPCION','ACTIVO'),(4,2,'MEDICO','ACTIVO')")
        conn.exec_driver_sql("""INSERT INTO usuarios
          (id_usuario,id_clinica,id_rol,nombres,apellidos,correo,password_hash,estado,notificaciones_push,notificaciones_email,notificaciones_sms)
          VALUES (1,1,1,'Medico','A','m1@test.invalid','x','activo',1,1,0),
          (2,1,1,'Medico','B','m2@test.invalid','x','activo',1,1,0),
          (3,1,2,'Paciente','A','p1@test.invalid','x','activo',1,1,0),
          (4,1,2,'Paciente','B','p2@test.invalid','x','activo',1,1,0),
          (5,2,4,'Medico','C','m3@test.invalid','x','activo',1,1,0),
          (6,1,3,'Recepcion','A','r@test.invalid','x','activo',1,1,0)""")
        for i, permission in enumerate(("treatments:read", "treatments:write", "treatments:dose:record", "treatments:notify:read"), 1):
            conn.exec_driver_sql("INSERT INTO permisos (id_permiso,nombre,modulo,accion,estado) VALUES (?,?,?,?,?)", (i, permission, "treatments", permission, "ACTIVO"))
        for role, permission in ((1,1),(1,2),(1,4),(2,1),(2,3),(2,4),(4,1),(4,2),(4,4)):
            conn.exec_driver_sql("INSERT INTO rol_permisos (id_rol,id_permiso) VALUES (?,?)", (role, permission))
        conn.exec_driver_sql("""INSERT INTO pacientes (id_paciente,id_clinica,id_usuario,nombres,apellidos,ci,fecha_nacimiento,genero,telefono,estado)
          VALUES (10,1,3,'Paciente','A','111','1990-01-01','F','70000001','ACTIVO'),
                 (11,1,4,'Paciente','B','222','1990-01-01','F','70000002','ACTIVO')""")
        conn.exec_driver_sql("INSERT INTO medicos (id_medico,id_clinica,id_usuario,matricula_profesional,estado) VALUES (21,1,1,'M1','activo'),(22,1,2,'M2','activo'),(23,2,5,'M3','activo')")
        conn.exec_driver_sql("INSERT INTO citas (id_cita,id_clinica,id_paciente,id_medico,estado) VALUES (31,1,10,21,'FINALIZADA')")
        conn.exec_driver_sql("INSERT INTO historias_clinicas (id_historia,id_clinica,id_paciente,numero_historia) VALUES (41,1,10,'H1')")
        conn.exec_driver_sql("""INSERT INTO consultas (id_consulta,id_clinica,id_historia,id_cita,id_medico,motivo_consulta,sintomas,evolucion,plan_medico)
          VALUES (42,1,41,31,21,'Control','Sintomas','Estable','Tratamiento')""")
        conn.exec_driver_sql("INSERT INTO diagnosticos (id_diagnostico,id_consulta,codigo_cie,descripcion,tipo) VALUES (54,42,'A00','Diagnostico','DEFINITIVO')")
        conn.exec_driver_sql("""INSERT INTO recetas (id_receta,id_clinica,id_consulta,id_medico,id_paciente,folio,codigo_verificacion_hash,firma_digital,algoritmo_firma,key_id,version_payload,hash_pdf,fecha_vencimiento,estado)
          VALUES (81,1,42,21,10,'REC-1',?,'firma','ED25519','test',1,?,'2099-01-01','EMITIDA')""", ("a"*64,"b"*64))
        conn.exec_driver_sql("""INSERT INTO receta_detalle (id_receta_detalle,id_receta,nombre_medicamento_manual,medicamento_nombre,dosis,frecuencia,duracion,via_administracion,cantidad,indicaciones,posicion)
          VALUES (121,81,'Farmaco','Farmaco','500 mg','cada 8 horas','7 dias','ORAL',21,'Con alimentos',1)""")
        conn.exec_driver_sql("""INSERT INTO documentos_clinicos
          (id_documento,id_clinica,id_paciente,tipo_documento,titulo,archivo_url,hash_archivo,fecha_documento,estado)
          VALUES (91,1,10,'RECETA','Receta','test.pdf',?,'2026-01-01','ACTIVO')""", ("b"*64,))
        conn.exec_driver_sql("UPDATE recetas SET id_documento=91 WHERE id_receta=81")
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
            db.expunge(user)
        app.dependency_overrides[get_current_user] = lambda: user

    app.dependency_overrides[get_db] = db_dependency
    authenticate(1)
    with TestClient(app) as client:
        yield client, engine, authenticate
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    engine.dispose()


def payload(day, last_day=None):
    end = last_day or day
    return {"id_consulta": 42, "id_receta": 81, "fecha_inicio": day.isoformat(),
            "fecha_fin": end.isoformat(), "zona_horaria": "America/La_Paz", "notas": "Seguimiento",
            "medicamentos": [{"id_receta_detalle": 121, "fecha_inicio": day.isoformat(),
                               "fecha_fin": end.isoformat(), "horas_locales": ["06:00", "14:00", "22:00"],
                               "indicaciones": "Con alimentos"}]}


def make_plan(client, day, last_day=None):
    response = client.post("/api/v1/tratamientos", json=payload(day, last_day))
    assert response.status_code == 201, response.text
    return response.json()


def past_day():
    return datetime.now(ZoneInfo("America/La_Paz")).date() - timedelta(days=2)


def test_plan_cu16_y_aislamiento(scenario):
    client, _, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    assert plan["id_paciente"] == 10
    assert plan["id_diagnostico"] == 54
    assert plan["medicamentos"][0]["intervalo_horas"] == 8
    assert client.post("/api/v1/tratamientos", json=payload(day)).status_code == 409
    for user_id in (2, 4, 5):
        auth(user_id)
        assert client.get(f"/api/v1/tratamientos/{pid}").status_code == 404
    auth(6)
    assert client.get(f"/api/v1/tratamientos/{pid}").status_code == 403
    auth(3)
    assert client.get(f"/api/v1/tratamientos/{pid}").status_code == 200


def test_limite_inicial_del_plan_sin_receta(scenario):
    client, _, _ = scenario
    inicio = past_day()
    body = {"id_consulta": 42, "fecha_inicio": inicio.isoformat(),
            "fecha_fin": (inicio + timedelta(days=366)).isoformat(),
            "zona_horaria": "America/La_Paz", "medicamentos": []}
    response = client.post("/api/v1/tratamientos", json=body)
    assert response.status_code == 422
    body["fecha_fin"] = (inicio + timedelta(days=365)).isoformat()
    response = client.post("/api/v1/tratamientos", json=body)
    assert response.status_code == 201, response.text


def test_registro_idempotente_y_adherencia(scenario):
    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)
    response = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()})
    assert response.status_code == 200, response.text
    doses = response.json()["dosis"]
    assert len(doses) == 3
    first, second = doses[:2]
    url = f"/api/v1/tratamientos/dosis/{first['id_dosis']}/registros"
    body = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T06:00:00-04:00", "nota": "Sin molestias"}
    first_response = client.post(url, json=body, headers={"Idempotency-Key": "registro-1"})
    assert first_response.status_code == 200, first_response.text
    assert first_response.json()["puntual"] is True
    assert client.post(url, json=body, headers={"Idempotency-Key": "registro-1"}).json() == first_response.json()
    assert client.post(url, json={**body, "nota": "Cambio"}, headers={"Idempotency-Key": "registro-1"}).status_code == 409
    late = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T15:01:00-04:00"}
    response = client.post(f"/api/v1/tratamientos/dosis/{second['id_dosis']}/registros", json=late, headers={"Idempotency-Key": "registro-2"})
    assert response.status_code == 200, response.text
    assert response.json()["puntual"] is False
    metric = client.get(f"/api/v1/tratamientos/{pid}/adherencia").json()
    assert (metric["numerador_puntual"], metric["denominador_programado"], metric["porcentaje"], metric["nivel"]) == (1, 3, 33.3, "CRITICA")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE id_dosis = ?", (first["id_dosis"],)).scalar_one() == 1


def test_pauta_invalida_y_horario_de_verano(scenario):
    client, engine, _ = scenario
    day = past_day()
    invalid = payload(day)
    invalid["medicamentos"][0]["horas_locales"] = []
    assert client.post("/api/v1/tratamientos", json=invalid).status_code == 422
    ambiguous = payload(day)
    ambiguous.update(fecha_inicio="2027-03-14", fecha_fin="2027-03-14", zona_horaria="America/New_York")
    ambiguous["medicamentos"][0].update(fecha_inicio="2027-03-14", fecha_fin="2027-03-14", horas_locales=["02:30"])
    assert client.post("/api/v1/tratamientos", json=ambiguous).status_code == 422
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamientos").scalar_one() == 0


def test_plan_sin_receta_y_diagnostico_ambiguo(scenario):
    client, engine, _ = scenario
    day = past_day()
    request = payload(day)
    request.update(id_receta=None, medicamentos=[])
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO diagnosticos (id_diagnostico,id_consulta,codigo_cie,descripcion,tipo) VALUES (55,42,'B00','Otro','PRESUNTIVO')")
    assert client.post("/api/v1/tratamientos", json=request).status_code == 422
    request["id_diagnostico"] = 54
    assert client.post("/api/v1/tratamientos", json={**request, "id_clinica": 2}).status_code == 422
    response = client.post("/api/v1/tratamientos", json=request)
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["id_clinica"] == 1
    assert plan["medicamentos"] == []
    assert plan["adherencia"]["porcentaje"] is None
    assert plan["adherencia"]["nivel"] == "SIN_DATOS"


def test_receta_anulada_bloquea_registro(scenario):
    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)
    dose = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()}).json()["dosis"][0]
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE recetas SET estado='ANULADA' WHERE id_receta=81")
    response = client.post(f"/api/v1/tratamientos/dosis/{dose['id_dosis']}/registros",
                           json={"estado":"INGERIDA", "efectiva_en":f"{day.isoformat()}T06:00:00-04:00"},
                           headers={"Idempotency-Key":"anulada"})
    assert response.status_code == 409
    response = client.get(f"/api/v1/tratamientos/{pid}")
    assert response.status_code == 200
    assert response.json()["estado"] == "SUSPENDIDO_POR_RECETA"


def test_suspension_reactivacion_y_cierre_conservan_historia(scenario):
    client, _, auth = scenario
    day = past_day()
    future = datetime.now(ZoneInfo("America/La_Paz")).date() + timedelta(days=1)
    plan = make_plan(client, day, future)
    pid = plan["id_tratamiento"]
    med_id = plan["medicamentos"][0]["id_medicamento_plan"]
    endpoint = f"/api/v1/tratamientos/{pid}/medicamentos/{med_id}"
    before = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": future.isoformat()}).json()["dosis"]
    assert len(before) == 3
    response = client.post(f"{endpoint}/suspender", json={"motivo": "Suspensión por revisión clínica"})
    assert response.status_code == 200, response.text
    assert response.json()["medicamentos"][0]["estado"] == "SUSPENDIDO"
    assert client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": future.isoformat()}).json()["dosis"] == []
    history = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()}).json()["dosis"]
    assert len(history) == 3
    response = client.post(f"{endpoint}/reactivar", json={"motivo": "Reanudación indicada por médico"})
    assert response.status_code == 200, response.text
    after = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": future.isoformat()}).json()["dosis"]
    assert [d["id_dosis"] for d in after] == [d["id_dosis"] for d in before]
    response = client.post(f"/api/v1/tratamientos/{pid}/finalizar", json={"motivo": "Tratamiento finalizado clínicamente"})
    assert response.status_code == 200, response.text
    assert response.json()["estado"] == "FINALIZADO"
    assert client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": future.isoformat()}).json()["dosis"] == []
    auth(3)
    response = client.post(f"/api/v1/tratamientos/dosis/{history[0]['id_dosis']}/registros",
        json={"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T06:00:00-04:00"},
        headers={"Idempotency-Key": "despues-del-cierre"})
    assert response.status_code == 409


def test_prorroga_exige_indicar_medicamentos(scenario):
    client, _, _ = scenario
    day = past_day()
    future = datetime.now(ZoneInfo("America/La_Paz")).date() + timedelta(days=1)
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    med_id = plan["medicamentos"][0]["id_medicamento_plan"]
    response = client.patch(f"/api/v1/tratamientos/{pid}/vigencia", json={
        "fecha_fin": future.isoformat(), "motivo": "Extender seguimiento clínico", "medicamentos": []})
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": future.isoformat()}).json()["dosis"] == []
    next_day = future + timedelta(days=1)
    response = client.patch(f"/api/v1/tratamientos/{pid}/vigencia", json={
        "fecha_fin": next_day.isoformat(), "motivo": "Extender pauta farmacológica",
        "medicamentos": [{"id_medicamento_plan": med_id, "fecha_fin": next_day.isoformat()}]})
    assert response.status_code == 200, response.text
    assert len(client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": future.isoformat()}).json()["dosis"]) == 3


def test_error_auditoria_revierte_toma_y_evento(scenario, monkeypatch):
    from app.modules.medical_records.tratamientos import service

    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)
    dose = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()}).json()["dosis"][0]

    def fail_audit(*args, **kwargs):
        raise RuntimeError("fallo de auditoria simulado")

    monkeypatch.setattr(service, "registrar_auditoria", fail_audit)
    with pytest.raises(RuntimeError, match="fallo de auditoria simulado"):
        client.post(f"/api/v1/tratamientos/dosis/{dose['id_dosis']}/registros",
            json={"estado":"INGERIDA", "efectiva_en":f"{day.isoformat()}T06:00:00-04:00"},
            headers={"Idempotency-Key": "rollback"})
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT estado FROM tratamiento_dosis WHERE id_dosis=?", (dose["id_dosis"],)).scalar_one() == "PENDIENTE"
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE id_dosis=?", (dose["id_dosis"],)).scalar_one() == 0


def test_ingesta_anticipada_no_inflaciona_adherencia(scenario, monkeypatch):
    from app.modules.medical_records.tratamientos import service

    client, _, auth = scenario
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "now_utc", lambda: now)
    day = date(2026, 10, 29)
    request = payload(day)
    request["medicamentos"][0]["horas_locales"] = ["08:20"]
    response = client.post("/api/v1/tratamientos", json=request)
    assert response.status_code == 201, response.text
    pid = response.json()["id_tratamiento"]
    auth(3)
    dose = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()}).json()["dosis"][0]
    response = client.post(f"/api/v1/tratamientos/dosis/{dose['id_dosis']}/registros",
        json={"estado":"INGERIDA", "efectiva_en":"2026-10-29T08:00:00-04:00"},
        headers={"Idempotency-Key":"anticipada"})
    assert response.status_code == 200, response.text
    metric = client.get(f"/api/v1/tratamientos/{pid}/adherencia").json()
    assert (metric["numerador_puntual"], metric["denominador_programado"], metric["porcentaje"]) == (0, 0, None)
    monkeypatch.setattr(service, "now_utc", lambda: now + timedelta(minutes=20))
    metric = client.get(f"/api/v1/tratamientos/{pid}/adherencia").json()
    assert (metric["numerador_puntual"], metric["denominador_programado"], metric["porcentaje"]) == (1, 1, 100.0)


def test_lecturas_clinicas_auditadas_sin_contenido_clinico(scenario):
    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)
    for path in ("/api/v1/tratamientos", f"/api/v1/tratamientos/{pid}",
                 f"/api/v1/tratamientos/{pid}/cronograma?fecha={day.isoformat()}",
                 f"/api/v1/tratamientos/{pid}/adherencia"):
        response = client.get(path)
        assert response.status_code == 200, response.text
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("""SELECT id_clinica,id_usuario,direccion_ip,descripcion,datos_anteriores,datos_nuevos
          FROM auditoria WHERE tabla_afectada='tratamientos' AND accion='SELECT'""").all()
        assert len(rows) == 4
        assert all(row[0] == 1 and row[1] == 3 and row[2] for row in rows)
        assert all("Farmaco" not in str(row) and "Diagnostico" not in str(row) and "Seguimiento" not in str(row) for row in rows)


def test_anulacion_cu16_suspende_plan_en_la_misma_transaccion(scenario):
    client, engine, _ = scenario
    day = past_day()
    future = datetime.now(ZoneInfo("America/La_Paz")).date() + timedelta(days=1)
    plan = make_plan(client, day, future)
    pid = plan["id_tratamiento"]
    response = client.post("/api/v1/recetas/81/anular", json={"motivo_anulacion":"Corrección clínica necesaria"})
    assert response.status_code == 200, response.text
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT estado FROM recetas WHERE id_receta=81").scalar_one() == "ANULADA"
        assert conn.exec_driver_sql("SELECT estado FROM tratamientos WHERE id_tratamiento=?", (pid,)).scalar_one() == "SUSPENDIDO_POR_RECETA"
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE id_tratamiento=? AND accion='SUSPENDER_POR_RECETA'", (pid,)).scalar_one() == 1
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM auditoria WHERE tabla_afectada='tratamientos' AND accion='UPDATE' AND descripcion='SUSPENDER_POR_RECETA' AND id_usuario=1").scalar_one() == 1
    assert client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": future.isoformat()}).json()["dosis"] == []


def test_error_auditoria_al_anular_revierte_receta_y_plan(scenario, monkeypatch):
    from app.modules.medical_records.tratamientos import service

    client, engine, _ = scenario
    plan = make_plan(client, past_day())
    pid = plan["id_tratamiento"]

    def fail_audit(*args, **kwargs):
        raise RuntimeError("fallo auditoria CU17")

    monkeypatch.setattr(service, "registrar_auditoria", fail_audit)
    with pytest.raises(RuntimeError, match="fallo auditoria CU17"):
        client.post("/api/v1/recetas/81/anular", json={"motivo_anulacion":"Corrección clínica necesaria"})
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT estado FROM recetas WHERE id_receta=81").scalar_one() == "EMITIDA"
        assert conn.exec_driver_sql("SELECT estado FROM tratamientos WHERE id_tratamiento=?", (pid,)).scalar_one() == "ACTIVO"
        assert conn.exec_driver_sql("SELECT estado FROM documentos_clinicos WHERE id_documento=91").scalar_one() == "ACTIVO"
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE accion='SUSPENDER_POR_RECETA'").scalar_one() == 0


def test_semaforo_corresponde_a_porcentaje_redondeado(scenario, monkeypatch):
    from app.modules.medical_records.tratamientos import service

    client, engine, _ = scenario
    start = date(2026, 1, 1)
    last = start + timedelta(days=104)
    now = datetime(last.year, last.month, last.day, 7, 0, tzinfo=timezone.utc)  # 03:00 local
    monkeypatch.setattr(service, "now_utc", lambda: now)
    request = payload(start, last)
    request["medicamentos"][0]["horas_locales"] = [f"{hour:02}:00" for hour in range(24)]
    response = client.post("/api/v1/tratamientos", json=request)
    assert response.status_code == 201, response.text
    pid = response.json()["id_tratamiento"]
    with engine.begin() as conn:
        conn.exec_driver_sql("""UPDATE tratamiento_dosis SET estado='INGERIDA', efectiva_en_utc=programada_en_utc
            WHERE id_dosis IN (SELECT id_dosis FROM tratamiento_dosis ORDER BY programada_en_utc LIMIT 1999)""")
    response = client.get(f"/api/v1/tratamientos/{pid}/adherencia")
    assert response.status_code == 200, response.text
    metric = response.json()
    assert (metric["numerador_puntual"], metric["denominador_programado"]) == (1999, 2500)
    assert (metric["porcentaje"], metric["nivel"]) == (80.0, "OPTIMA")


def test_garantias_idempotencia_y_concurrencia(scenario, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from app.modules.medical_records.tratamientos import service

    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)

    response = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()})
    assert response.status_code == 200, response.text
    doses = response.json()["dosis"]
    first, second = doses[0], doses[1]
    url = f"/api/v1/tratamientos/dosis/{first['id_dosis']}/registros"
    body = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T06:00:00-04:00", "nota": "Sin molestias"}

    # 1. Registro inicial exitoso
    res1 = client.post(url, json=body, headers={"Idempotency-Key": "idemp-test-1"})
    assert res1.status_code == 200, res1.text
    initial_data = res1.json()

    # 2. Reintento idéntico devuelve exactamente la respuesta previa (HTTP 200) sin nuevo evento ni efectos colaterales
    res2 = client.post(url, json=body, headers={"Idempotency-Key": "idemp-test-1"})
    assert res2.status_code == 200
    assert res2.json() == initial_data
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE id_dosis = ?", (first["id_dosis"],)).scalar_one() == 1

    # 3. Clave reutilizada con cuerpo distinto devuelve HTTP 409 y code TREATMENT_IDEMPOTENCY_CONFLICT
    res3 = client.post(url, json={**body, "nota": "Cuerpo modificado"}, headers={"Idempotency-Key": "idemp-test-1"})
    assert res3.status_code == 409
    assert res3.json() == {
        "detail": "Clave de idempotencia reutilizada con otros datos",
        "code": "TREATMENT_IDEMPOTENCY_CONFLICT"
    }

    # 4. Cambio posterior legítimo con clave NUEVA conserva eventos previos y actualiza la dosis
    correction_body = {"estado": "OMITIDA", "nota": "Corrección: dosis no tomada"}
    res4 = client.post(url, json=correction_body, headers={"Idempotency-Key": "idemp-test-correccion"})
    assert res4.status_code == 200
    assert res4.json()["estado"] == "OMITIDA"
    assert res4.json()["nota"] == "Corrección: dosis no tomada"
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE id_dosis = ?", (first["id_dosis"],)).scalar_one() == 2
        events = conn.exec_driver_sql(
            "SELECT accion, estado_anterior, estado_nuevo FROM tratamiento_eventos WHERE id_dosis = ? ORDER BY id_evento",
            (first["id_dosis"],)
        ).fetchall()
        assert events[0] == ("REGISTRAR_DOSIS", "PENDIENTE", "INGERIDA")
        assert events[1] == ("REGISTRAR_DOSIS", "INGERIDA", "OMITIDA")

    # 5. Manejo de IntegrityError ante colisión concurrente con la misma clave
    url2 = f"/api/v1/tratamientos/dosis/{second['id_dosis']}/registros"
    body2 = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T14:00:00-04:00"}
    res_orig = client.post(url2, json=body2, headers={"Idempotency-Key": "idemp-conc-key"})
    assert res_orig.status_code == 200

    def raise_integrity(*args, **kwargs):
        raise IntegrityError("duplicate key", params=None, orig=Exception())

    monkeypatch.setattr(service, "_event", raise_integrity)

    # 5a. Carrera concurrente con mismo payload: recupera respuesta previa (HTTP 200)
    res_conc_same = client.post(url2, json=body2, headers={"Idempotency-Key": "idemp-conc-key"})
    assert res_conc_same.status_code == 200
    assert res_conc_same.json() == res_orig.json()

    # 5b. Carrera concurrente con payload distinto: responde 409 con TREATMENT_IDEMPOTENCY_CONFLICT
    res_conc_diff = client.post(url2, json={**body2, "nota": "Distinto"}, headers={"Idempotency-Key": "idemp-conc-key"})
    assert res_conc_diff.status_code == 409
    assert res_conc_diff.json()["code"] == "TREATMENT_IDEMPOTENCY_CONFLICT"


def test_concurrencia_colision_real_unique_constraint_mismo_y_distinto_cuerpo(scenario, monkeypatch):
    """Verifica colisión real contra el constraint uq_tratamiento_evento_idempotencia de la base de datos."""
    from sqlalchemy.exc import IntegrityError
    from app.modules.medical_records.tratamientos import service
    from app.modules.medical_records.tratamientos.models import TratamientoEvento

    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)

    doses = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()}).json()["dosis"]
    dose = doses[0]
    url = f"/api/v1/tratamientos/dosis/{dose['id_dosis']}/registros"
    body = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T06:00:00-04:00", "nota": "Toma concurrente"}

    # Caso A: Carrera con mismo cuerpo.
    # Se simula que una transacción ganadora insertó y confirmó el evento justo antes de que
    # la transacción perdedora ejecute db.flush(), provocando IntegrityError real en el motor DB.
    original_event = service._event

    def racing_winner_same_event(db, plan_obj, user_obj, role_str, ip_str, action_str, **kwargs):
        ParallelSession = sessionmaker(bind=engine)
        with ParallelSession() as s:
            winner = TratamientoEvento(
                id_clinica=plan_obj.id_clinica,
                id_tratamiento=plan_obj.id_tratamiento,
                id_dosis=kwargs.get("dose").id_dosis,
                id_medicamento_plan=kwargs.get("med").id_medicamento_plan,
                accion="REGISTRAR_DOSIS",
                id_usuario=user_obj.id_usuario,
                rol_actor=role_str,
                idempotencia_hash=kwargs.get("key_hash"),
                request_hash=kwargs.get("request_hash"),
                respuesta_json={"id_dosis": dose["id_dosis"], "estado": "INGERIDA", "winner_confirmed": True}
            )
            s.add(winner)
            s.commit()
        return original_event(db, plan_obj, user_obj, role_str, ip_str, action_str, **kwargs)

    monkeypatch.setattr(service, "_event", racing_winner_same_event)
    res_same = client.post(url, json=body, headers={"Idempotency-Key": "race-real-same"})
    assert res_same.status_code == 200, res_same.text
    assert res_same.json() == {"id_dosis": dose["id_dosis"], "estado": "INGERIDA", "winner_confirmed": True}

    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT COUNT(*) FROM tratamiento_eventos WHERE id_dosis = ? AND idempotencia_hash IS NOT NULL",
            (dose["id_dosis"],)
        ).scalar_one() == 1

    # Caso B: Carrera con distinto cuerpo.
    # El ganador confirmó con un request_hash diferente. La perdedora sufre IntegrityError
    # y al inspeccionar el evento previo constata el conflicto -> 409 TREATMENT_IDEMPOTENCY_CONFLICT.
    dose2 = doses[1]
    url2 = f"/api/v1/tratamientos/dosis/{dose2['id_dosis']}/registros"
    body2 = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T14:00:00-04:00", "nota": "Toma perdedora"}

    def racing_winner_diff_event(db, plan_obj, user_obj, role_str, ip_str, action_str, **kwargs):
        ParallelSession = sessionmaker(bind=engine)
        with ParallelSession() as s:
            winner = TratamientoEvento(
                id_clinica=plan_obj.id_clinica,
                id_tratamiento=plan_obj.id_tratamiento,
                id_dosis=kwargs.get("dose").id_dosis,
                id_medicamento_plan=kwargs.get("med").id_medicamento_plan,
                accion="REGISTRAR_DOSIS",
                id_usuario=user_obj.id_usuario,
                rol_actor=role_str,
                idempotencia_hash=kwargs.get("key_hash"),
                request_hash="OTRO_HASH_DE_CUERPO_DIFERENTE",
                respuesta_json={"id_dosis": dose2["id_dosis"], "estado": "INGERIDA", "first": True}
            )
            s.add(winner)
            s.commit()
        return original_event(db, plan_obj, user_obj, role_str, ip_str, action_str, **kwargs)

    monkeypatch.setattr(service, "_event", racing_winner_diff_event)
    res_diff = client.post(url2, json=body2, headers={"Idempotency-Key": "race-real-diff"})
    assert res_diff.status_code == 409
    assert res_diff.json() == {
        "detail": "Conflicto al registrar la dosis",
        "code": "TREATMENT_IDEMPOTENCY_CONFLICT"
    }

    # Caso C: IntegrityError sin evento previo (por ejemplo fallo de integridad no idempotente)
    dose3 = doses[2]
    url3 = f"/api/v1/tratamientos/dosis/{dose3['id_dosis']}/registros"
    body3 = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T22:00:00-04:00"}

    def raise_unexpected_integrity(*args, **kwargs):
        raise IntegrityError("foreign key or check violation", params=None, orig=Exception())

    monkeypatch.setattr(service, "_event", raise_unexpected_integrity)
    res_unexp = client.post(url3, json=body3, headers={"Idempotency-Key": "race-unexp-key"})
    assert res_unexp.status_code == 409
    assert res_unexp.json() == {
        "detail": "Conflicto al registrar la dosis",
        "code": "TREATMENT_IDEMPOTENCY_CONFLICT"
    }


def test_validacion_cabecera_idempotencia_y_recuperacion_tras_errores(scenario):
    """Verifica validación rigurosa de Idempotency-Key y que reintentos tras errores 422/409 no bloquean la clave."""
    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)

    doses = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()}).json()["dosis"]
    dose = doses[0]
    url = f"/api/v1/tratamientos/dosis/{dose['id_dosis']}/registros"
    valid_body = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T06:00:00-04:00", "nota": "Ok"}

    # 1. Cabecera ausente
    res_no_key = client.post(url, json=valid_body)
    assert res_no_key.status_code == 422
    assert res_no_key.json() == {
        "detail": "Idempotency-Key debe tener entre 1 y 128 caracteres",
        "code": "TREATMENT_VALIDATION"
    }

    # 2. Cabecera vacía o solo espacios en blanco
    for empty in ("", "   ", "\t  "):
        res_empty = client.post(url, json=valid_body, headers={"Idempotency-Key": empty})
        assert res_empty.status_code == 422
        assert res_empty.json()["code"] == "TREATMENT_VALIDATION"

    # 3. Cabecera excesiva (> 128 caracteres)
    res_long = client.post(url, json=valid_body, headers={"Idempotency-Key": "a" * 129})
    assert res_long.status_code == 422
    assert res_long.json()["code"] == "TREATMENT_VALIDATION"

    # 4. Longitudes límite válidas (1 caracter y 128 caracteres)
    key_min = "x"
    res_min = client.post(url, json=valid_body, headers={"Idempotency-Key": key_min})
    assert res_min.status_code == 200

    dose2 = doses[1]
    url2 = f"/api/v1/tratamientos/dosis/{dose2['id_dosis']}/registros"
    valid_body2 = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T14:00:00-04:00"}
    key_max = "k" * 128
    res_max = client.post(url2, json=valid_body2, headers={"Idempotency-Key": key_max})
    assert res_max.status_code == 200

    # 5. Clave nueva tras rechazo o corrección:
    # Si un intento previo fue rechazado (por ej. hora efectiva futura), no genera evento
    # y la misma clave u otra nueva puede registrar la dosis legítimamente corregida.
    dose3 = doses[2]
    url3 = f"/api/v1/tratamientos/dosis/{dose3['id_dosis']}/registros"
    future_time = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    invalid_future = {"estado": "INGERIDA", "efectiva_en": future_time}

    res_rejected = client.post(url3, json=invalid_future, headers={"Idempotency-Key": "key-retry-test"})
    assert res_rejected.status_code == 422
    assert res_rejected.json()["code"] == "TREATMENT_VALIDATION"

    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE id_dosis = ?", (dose3["id_dosis"],)).scalar_one() == 0

    corrected_body = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T22:00:00-04:00", "nota": "Corregido"}
    # La misma clave con otro cuerpo debe dar 409 IDEMPOTENCY_CONFLICT
    res_conflict = client.post(url3, json=corrected_body, headers={"Idempotency-Key": "key-retry-test"})
    assert res_conflict.status_code == 409
    assert res_conflict.json()["code"] == "TREATMENT_IDEMPOTENCY_CONFLICT"

    # Con una clave nueva y limpia, la toma corregida se registra exitosamente
    res_retry = client.post(url3, json=corrected_body, headers={"Idempotency-Key": "key-retry-test-corregida"})
    assert res_retry.status_code == 200
    assert res_retry.json()["estado"] == "INGERIDA"

    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE id_dosis = ?", (dose3["id_dosis"],)).scalar_one() == 1


def test_respuestas_uniformes_de_error_y_control_de_acceso_dosis(scenario):
    """Verifica códigos y esquemas de error uniformes (403, 404, 409, 422) y alcance del Idempotency-Key."""
    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)

    doses = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()}).json()["dosis"]
    dose = doses[0]
    url = f"/api/v1/tratamientos/dosis/{dose['id_dosis']}/registros"
    valid_body = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T06:00:00-04:00"}

    # 1. 404 NOT_FOUND para dosis inexistente
    res_404 = client.post("/api/v1/tratamientos/dosis/999999/registros", json=valid_body, headers={"Idempotency-Key": "key-404"})
    assert res_404.status_code == 404
    assert res_404.json() == {"detail": "Dosis no encontrada", "code": "TREATMENT_NOT_FOUND"}

    # 2. 404 NOT_FOUND cuando otro paciente (id_usuario 4) intenta registrar la dosis de id_usuario 3
    auth(4)
    res_other_patient = client.post(url, json=valid_body, headers={"Idempotency-Key": "key-sec"})
    assert res_other_patient.status_code == 404
    assert res_other_patient.json() == {"detail": "Dosis no encontrada", "code": "TREATMENT_NOT_FOUND"}

    # 3. 403 FORBIDDEN si un médico o recepción intenta invocar el endpoint exclusivo de paciente
    auth(1)  # Médico tratante (sin permiso treatments:dose:record)
    res_med = client.post(url, json=valid_body, headers={"Idempotency-Key": "key-med"})
    assert res_med.status_code == 403
    assert res_med.json() == {"detail": "Acceso a tratamientos denegado", "code": "TREATMENT_FORBIDDEN"}

    # Si se concediera el permiso al rol MEDICO, la regla de dominio sigue rechazando
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (1, 3)")
    res_med_perm = client.post(url, json=valid_body, headers={"Idempotency-Key": "key-med2"})
    assert res_med_perm.status_code == 403
    assert res_med_perm.json() == {"detail": "Solo el paciente titular puede registrar tomas", "code": "TREATMENT_FORBIDDEN"}

    auth(6)  # Recepción
    res_rec = client.post(url, json=valid_body, headers={"Idempotency-Key": "key-rec"})
    assert res_rec.status_code == 403
    assert res_rec.json()["code"] == "TREATMENT_FORBIDDEN"

    # 4. 422 VALIDATION al intentar omitir una dosis futura
    auth(3)
    from app.modules.medical_records.tratamientos import service
    monkeypatch = pytest.MonkeyPatch()
    past_simulated = datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "now_utc", lambda: past_simulated)
    try:
        res_omit_future = client.post(url, json={"estado": "OMITIDA"}, headers={"Idempotency-Key": "key-omit-fut"})
        assert res_omit_future.status_code == 422
        assert res_omit_future.json() == {
            "detail": "No se puede omitir una dosis futura",
            "code": "TREATMENT_VALIDATION"
        }
    finally:
        monkeypatch.undo()

    # 5. 422 VALIDATION cuando hora efectiva es previa al inicio del plan
    plan_start_date = date.fromisoformat(plan["fecha_inicio"]) - timedelta(days=5)
    before_plan = datetime.combine(plan_start_date, datetime.min.time(), tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    res_before = client.post(url, json={"estado": "INGERIDA", "efectiva_en": before_plan}, headers={"Idempotency-Key": "key-before"})
    assert res_before.status_code == 422
    assert res_before.json() == {
        "detail": "La hora efectiva está fuera del período permitido",
        "code": "TREATMENT_VALIDATION"
    }

    # 6. Idempotency-Key compartida entre DOSIS DIFERENTES no colisiona
    res_dose1 = client.post(url, json=valid_body, headers={"Idempotency-Key": "shared-dose-key"})
    assert res_dose1.status_code == 200

    dose1_next = doses[1]
    url_dose1_next = f"/api/v1/tratamientos/dosis/{dose1_next['id_dosis']}/registros"
    body_dose1_next = {"estado": "INGERIDA", "efectiva_en": f"{day.isoformat()}T14:00:00-04:00"}
    res_dose2 = client.post(url_dose1_next, json=body_dose1_next, headers={"Idempotency-Key": "shared-dose-key"})
    assert res_dose2.status_code == 200

    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM tratamiento_eventos WHERE idempotencia_hash IS NOT NULL").scalar_one() == 2


def test_consulta_idempotencia_recuperacion_y_control_acceso(scenario):
    """Verifica el endpoint GET de consulta de idempotencia para recuperación segura sin reenviar datos clínicos."""
    client, engine, auth = scenario
    day = past_day()
    plan = make_plan(client, day)
    pid = plan["id_tratamiento"]
    auth(3)  # Paciente titular de clínica 1

    doses = client.get(f"/api/v1/tratamientos/{pid}/cronograma", params={"fecha": day.isoformat()}).json()["dosis"]
    dose = doses[0]
    id_dosis = dose["id_dosis"]
    url_base = f"/api/v1/tratamientos/dosis/{id_dosis}/registros"

    # 1. Consulta de operación no registrada / aún sin confirmar (confirmado=False, dosis=None)
    res_not_registered = client.get(f"{url_base}/idempotencia/clave-no-registrada")
    assert res_not_registered.status_code == 200, res_not_registered.text
    data_not_reg = res_not_registered.json()
    assert data_not_reg["confirmado"] is False
    assert data_not_reg["en_curso"] is False
    assert data_not_reg["rechazado"] is False
    assert data_not_reg["estado"] == "NO_INICIADA"
    assert data_not_reg["id_dosis"] == id_dosis
    assert data_not_reg["idempotency_key"] == "clave-no-registrada"
    assert data_not_reg["dosis"] is None
    assert data_not_reg["mensaje"] is None
    assert "generacion" in data_not_reg

    # 2. Registrar la toma exitosamente con Idempotency-Key
    valid_body = {
        "estado": "INGERIDA",
        "efectiva_en": f"{day.isoformat()}T06:00:00-04:00",
        "nota": "Toma confirmada para recuperacion",
    }
    post_res = client.post(url_base, json=valid_body, headers={"Idempotency-Key": "recuperacion-key-1"})
    assert post_res.status_code == 200, post_res.text
    recorded_dose = post_res.json()

    # 3. Consulta de operación confirmada (confirmado=True, datos de dosis preservados)
    res_confirmed = client.get(f"{url_base}/idempotencia/recuperacion-key-1")
    assert res_confirmed.status_code == 200, res_confirmed.text
    data_conf = res_confirmed.json()
    assert data_conf["confirmado"] is True
    assert data_conf["en_curso"] is False
    assert data_conf["rechazado"] is False
    assert data_conf["estado"] == "CONFIRMADA"
    assert data_conf["id_dosis"] == id_dosis
    assert data_conf["idempotency_key"] == "recuperacion-key-1"
    assert data_conf["dosis"] == recorded_dose
    assert data_conf["mensaje"] is None
    assert "generacion" in data_conf

    # 4. Aislamiento multiclínica y paciente ajeno (404)
    # Paciente ajeno en la misma clínica (id_usuario 4)
    auth(4)
    res_foreign_patient = client.get(f"{url_base}/idempotencia/recuperacion-key-1")
    assert res_foreign_patient.status_code == 404
    assert res_foreign_patient.json() == {"detail": "Dosis no encontrada", "code": "TREATMENT_NOT_FOUND"}

    # Dosis inexistente
    auth(3)
    res_nonexistent = client.get("/api/v1/tratamientos/dosis/999999/registros/idempotencia/recuperacion-key-1")
    assert res_nonexistent.status_code == 404
    assert res_nonexistent.json() == {"detail": "Dosis no encontrada", "code": "TREATMENT_NOT_FOUND"}

    # Multiclínica: usuario de otra clínica (médico en clínica 2, usuario 5)
    auth(5)
    res_other_tenant = client.get(f"{url_base}/idempotencia/recuperacion-key-1")
    assert res_other_tenant.status_code in (403, 404)

    # 5. Usuario no paciente (médico u otro rol) intentando consultar idempotencia (403)
    auth(1)  # Médico tratante en la misma clínica
    res_doctor = client.get(f"{url_base}/idempotencia/recuperacion-key-1")
    assert res_doctor.status_code == 403
    assert res_doctor.json()["code"] == "TREATMENT_FORBIDDEN"

    # Médico con permiso treatments:dose:record forzado en rol sigue siendo rechazado por regla de dominio (solo PACIENTE)
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT OR IGNORE INTO rol_permisos (id_rol, id_permiso) VALUES (1, 3)")
    res_doctor_perm = client.get(f"{url_base}/idempotencia/recuperacion-key-1")
    assert res_doctor_perm.status_code == 403
    assert res_doctor_perm.json() == {
        "detail": "Solo el paciente titular puede registrar tomas",
        "code": "TREATMENT_FORBIDDEN",
    }

    auth(6)  # Recepción
    res_reception = client.get(f"{url_base}/idempotencia/recuperacion-key-1")
    assert res_reception.status_code == 403
    assert res_reception.json()["code"] == "TREATMENT_FORBIDDEN"

    # 6. Clave de idempotencia inválida/vacía (422)
    auth(3)
    # Clave vacía en ruta
    res_empty = client.get(f"{url_base}/idempotencia/")
    assert res_empty.status_code == 422
    assert res_empty.json() == {
        "detail": "Idempotency-Key debe tener entre 1 y 128 caracteres",
        "code": "TREATMENT_VALIDATION",
    }

    # Clave con solo espacios en blanco
    for blank in ("%20", "%20%20%20", "%09"):
        res_blank = client.get(f"{url_base}/idempotencia/{blank}")
        assert res_blank.status_code == 422
        assert res_blank.json() == {
            "detail": "Idempotency-Key debe tener entre 1 y 128 caracteres",
            "code": "TREATMENT_VALIDATION",
        }

    # Clave excesiva (> 128 caracteres)
    res_excessive = client.get(f"{url_base}/idempotencia/{'a' * 129}")
    assert res_excessive.status_code == 422
    assert res_excessive.json() == {
        "detail": "Idempotency-Key debe tener entre 1 y 128 caracteres",
        "code": "TREATMENT_VALIDATION",
    }

    # Longitudes límite válidas (1 caracter y 128 caracteres)
    res_min = client.get(f"{url_base}/idempotencia/x")
    assert res_min.status_code == 200
    assert res_min.json()["confirmado"] is False
    assert res_min.json()["idempotency_key"] == "x"

    res_max = client.get(f"{url_base}/idempotencia/{'k' * 128}")
    assert res_max.status_code == 200
    assert res_max.json()["confirmado"] is False
    assert res_max.json()["idempotency_key"] == "k" * 128
