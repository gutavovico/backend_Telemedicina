"""Pruebas de alertas CU17 y entrega por dispositivo sin proveedor externo."""
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # registra las tablas relacionadas en metadata
from app.core.database import Base, get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.tratamientos import avisos, service
from app.modules.medical_records.tratamientos.avisos_models import (
    TratamientoAviso, TratamientoCursor, TratamientoDispositivo, TratamientoEntregaPush,
)
from app.modules.medical_records.tratamientos.models import Tratamiento, TratamientoDosis, TratamientoEvento, TratamientoMedicamento


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)()
    db.execute(text("INSERT INTO clinicas (id_clinica,nombre,estado) VALUES (1,'Clínica','ACTIVO')"))
    db.execute(text("INSERT INTO roles (id_rol,nombre,estado) VALUES (1,'MEDICO','ACTIVO'),(2,'PACIENTE','ACTIVO')"))
    db.execute(text("""INSERT INTO usuarios (id_usuario,id_clinica,id_rol,nombres,apellidos,correo,password_hash,
        estado,token_version,notificaciones_push,notificaciones_email,notificaciones_sms) VALUES
        (1,1,1,'M','M','m@example.test','x','ACTIVO',0,1,0,0),
        (2,1,2,'P','P','p@example.test','x','ACTIVO',0,1,0,0)"""))
    db.execute(text("""INSERT INTO pacientes (id_paciente,id_clinica,id_usuario,nombres,apellidos,ci,
        fecha_nacimiento,genero,telefono,estado) VALUES (10,1,2,'P','P','123','1990-01-01','F','1','ACTIVO')"""))
    db.execute(text("INSERT INTO medicos (id_medico,id_usuario,matricula_profesional,estado) VALUES (3,1,'123','ACTIVO')"))
    db.execute(text("""INSERT INTO recetas (id_receta,id_clinica,id_consulta,id_medico,id_paciente,folio,
        codigo_verificacion_hash,firma_digital,algoritmo_firma,key_id,version_payload,hash_pdf,fecha_vencimiento,estado)
        VALUES (1,1,1,3,10,'R1','hash','firma','ED25519','key',1,'hash','2027-01-01','EMITIDA')"""))
    plan = Tratamiento(id_tratamiento=1, id_clinica=1, id_consulta=1, id_receta=1, id_diagnostico=1,
                       id_paciente=10, id_medico=3, fecha_inicio=date(2026, 10, 1), fecha_fin=date(2026, 12, 1),
                       zona_horaria="America/La_Paz", estado="ACTIVO")
    med = TratamientoMedicamento(id_medicamento_plan=1, id_clinica=1, id_tratamiento=1, id_receta_detalle=1,
                                medicamento_nombre="Medicina", dosis="1", via_administracion="ORAL",
                                frecuencia_texto_receta="diaria", duracion_texto_receta="un mes",
                                fecha_inicio=date(2026, 10, 1), fecha_fin=date(2026, 12, 1),
                                horas_locales=["08:00"], estado="ACTIVO")
    db.add_all([plan, med])
    db.commit()
    monkeypatch.setattr(avisos, "_receta_valida", lambda db, plan: True)
    monkeypatch.setattr(avisos.settings, "CU17_DEVICE_TOKEN_KEY", SecretStr(Fernet.generate_key().decode()))
    yield db
    db.close()
    engine.dispose()


def _dose(db, scheduled, state="PENDIENTE", effective=None):
    dose = TratamientoDosis(id_clinica=1, id_medicamento_plan=1, programada_en_utc=scheduled,
                            estado=state, efectiva_en_utc=effective)
    db.add(dose)
    db.flush()
    return dose


def test_avisos_son_unicos_y_riesgo_aparece_tras_tres_dosis(db):
    now = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    for hours in (50, 26, 2):
        _dose(db, now - timedelta(hours=hours))
    future = _dose(db, now + timedelta(minutes=15))
    assert avisos.generar_avisos(db, now=now) == 6
    assert avisos.generar_avisos(db, now=now) == 0
    rows = db.execute(select(TratamientoAviso)).scalars().all()
    assert len(rows) == 6
    assert sum(row.tipo == "RIESGO_ABANDONO" for row in rows) == 2
    assert {row.id_usuario for row in rows if row.tipo == "RIESGO_ABANDONO"} == {1, 2}
    assert sum(row.tipo == "RECORDATORIO" and row.id_dosis == future.id_dosis for row in rows) == 1
    assert all(row.canal == "WEB" and row.estado == "PENDIENTE" for row in rows)


def test_entregas_reintentan_solo_dispositivos_fallidos(db):
    now = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    for token in ("device-a", "device-b"):
        db.add(TratamientoDispositivo(id_clinica=1, id_usuario=2, token_hash=avisos.hash_token(token),
                                     token_cifrado=avisos.cifrar_token(token), plataforma="ANDROID", activo=True))
    db.flush()
    _dose(db, now + timedelta(minutes=15))
    assert avisos.generar_avisos(db, now=now) == 2
    calls = []

    def sender(token, *args):
        calls.append(token)
        if token == "device-b" and calls.count("device-b") == 1:
            raise RuntimeError("provider error must never appear in persistence")

    assert avisos.despachar_push(db, now=now, sender=sender) == 1
    push = db.execute(select(TratamientoAviso).where(TratamientoAviso.canal == "PUSH")).scalar_one()
    assert push.estado == "FALLIDO"
    assert avisos.despachar_push(db, now=now + timedelta(seconds=30), sender=sender) == 0
    assert avisos.despachar_push(db, now=now + timedelta(seconds=61), sender=sender) == 1
    assert calls.count("device-a") == 1 and calls.count("device-b") == 2
    assert push.estado == "ENVIADO"
    assert all(row.estado == "ENVIADO" for row in db.execute(select(TratamientoEntregaPush)).scalars())


def test_receta_anulada_y_consentimiento_revocado_impiden_envio(db, monkeypatch):
    now = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    token = "device-a"
    db.add(TratamientoDispositivo(id_clinica=1, id_usuario=2, token_hash=avisos.hash_token(token),
                                 token_cifrado=avisos.cifrar_token(token), plataforma="ANDROID", activo=True))
    db.flush()
    _dose(db, now + timedelta(minutes=15))
    assert avisos.generar_avisos(db, now=now) == 2
    db.execute(text("UPDATE usuarios SET notificaciones_push=0 WHERE id_usuario=2"))
    db.expire_all()
    calls = []
    assert avisos.despachar_push(db, now=now, sender=lambda *args: calls.append(args)) == 0
    assert calls == []
    delivery = db.execute(select(TratamientoEntregaPush)).scalar_one()
    assert delivery.estado == "FALLIDO" and delivery.ultimo_error == "AVISO_NO_VIGENTE"
    monkeypatch.setattr(avisos, "_receta_valida", lambda db, plan: False)
    assert avisos.generar_avisos(db, now=now + timedelta(hours=3)) == 0


def test_recordatorio_fallido_no_se_reenvia_despues_de_la_toma(db):
    now = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    token = "device-a"
    db.add(TratamientoDispositivo(id_clinica=1, id_usuario=2, token_hash=avisos.hash_token(token),
                                 token_cifrado=avisos.cifrar_token(token), plataforma="ANDROID", activo=True))
    db.flush()
    _dose(db, now + timedelta(minutes=15))
    avisos.generar_avisos(db, now=now)
    def fallar(*args):
        raise RuntimeError("fallo")
    avisos.despachar_push(db, now=now, sender=fallar)
    calls = []
    avisos.despachar_push(db, now=now + timedelta(minutes=16), sender=lambda *args: calls.append(args))
    assert calls == []
    delivery = db.execute(select(TratamientoEntregaPush)).scalar_one()
    assert delivery.ultimo_error == "AVISO_NO_VIGENTE"


def test_worker_recupera_por_lotes_sin_perder_recordatorio_actual(db, monkeypatch):
    now = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    future = _dose(db, now + timedelta(minutes=15))
    calls = []
    monkeypatch.setattr(service, "materializar", lambda db, plan, start, end, now=None: calls.append((start, end)))
    result = avisos.ejecutar_ciclo(db, now=now, sender=lambda *args: None)
    cursor = db.execute(select(TratamientoCursor)).scalar_one()
    assert cursor.siguiente_fecha == date(2026, 11, 1)
    assert calls == [(date(2026, 11, 1), date(2026, 11, 8)), (date(2026, 10, 1), date(2026, 10, 31))]
    assert result["avisos"] == 1
    assert db.execute(select(TratamientoAviso).where(TratamientoAviso.id_dosis == future.id_dosis)).scalar_one().tipo == "RECORDATORIO"


def test_reconciliacion_audita_solo_con_usuario_sistema_de_la_clinica(db, monkeypatch):
    now = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    plan = db.get(Tratamiento, 1)
    dose = _dose(db, now + timedelta(hours=2))
    monkeypatch.setattr(avisos.settings, "CU17_SYSTEM_USER_IDS_JSON", '{"1": 99}')
    assert avisos._reconciliar(db, plan, now) is False
    assert plan.estado == "ACTIVO" and dose.cancelada_en_utc is None
    db.execute(text("INSERT INTO roles (id_rol,id_clinica,nombre,estado) VALUES (9,1,'SISTEMA','ACTIVO')"))
    db.execute(text("""INSERT INTO usuarios (id_usuario,id_clinica,id_rol,nombres,apellidos,correo,password_hash,
        estado,token_version,notificaciones_push,notificaciones_email,notificaciones_sms) VALUES
        (99,1,9,'Servicio','CU17','worker@example.test','x','ACTIVO',0,0,0,0)"""))
    audit_calls = []
    monkeypatch.setattr(avisos, "registrar_auditoria", lambda db, **kw: audit_calls.append(kw))
    assert avisos._reconciliar(db, plan, now) is True
    db.refresh(dose)
    assert plan.estado == "SUSPENDIDO_POR_RECETA" and dose.cancelada_en_utc is not None
    event = db.execute(select(TratamientoEvento)).scalar_one()
    assert event.id_usuario == 99 and event.rol_actor == "SISTEMA"
    assert audit_calls[0]["id_usuario"] == 99 and audit_calls[0]["id_clinica"] == 1


def test_bandeja_aislada_y_token_cifrado_en_endpoints(db, monkeypatch):
    db.execute(text("INSERT INTO clinicas (id_clinica,nombre,estado) VALUES (2,'Otra','ACTIVO')"))
    db.execute(text("""INSERT INTO usuarios (id_usuario,id_clinica,id_rol,nombres,apellidos,correo,password_hash,
        estado,token_version,notificaciones_push,notificaciones_email,notificaciones_sms) VALUES
        (3,2,2,'Otro','P','otro@example.test','x','ACTIVO',0,1,0,0)"""))
    db.execute(text("""INSERT INTO pacientes (id_paciente,id_clinica,id_usuario,nombres,apellidos,ci,
        fecha_nacimiento,genero,telefono,estado) VALUES (20,2,3,'Otro','P','456','1990-01-01','F','2','ACTIVO')"""))
    db.execute(text("""INSERT INTO permisos (id_permiso,nombre,modulo,accion,estado)
        VALUES (1,'treatments:notify:read','treatments','notify','ACTIVO')"""))
    db.execute(text("INSERT INTO rol_permisos (id_rol,id_permiso) VALUES (2,1)"))
    now = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    _dose(db, now + timedelta(minutes=15))
    avisos.generar_avisos(db, now=now)
    notice = db.execute(select(TratamientoAviso)).scalar_one()
    patient = db.execute(select(Usuario).where(Usuario.id_usuario == 2)).scalar_one()
    other = db.execute(select(Usuario).where(Usuario.id_usuario == 3)).scalar_one()
    db.commit()
    app.main.app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app.main.app)
    try:
        app.main.app.dependency_overrides[get_current_user] = lambda: other
        assert client.get("/api/v1/tratamientos/avisos", headers={"X-Tenant-ID": "1"}).json()["total"] == 0
        assert client.patch(f"/api/v1/tratamientos/avisos/{notice.id_aviso}/leer").status_code == 404
        app.main.app.dependency_overrides[get_current_user] = lambda: patient
        assert client.get("/api/v1/tratamientos/avisos").json()["total"] == 1
        assert client.patch(f"/api/v1/tratamientos/avisos/{notice.id_aviso}/leer").json()["estado"] == "ENVIADO"
        monkeypatch.setattr(avisos, "push_configurado", lambda: True)
        response = client.post("/api/v1/tratamientos/dispositivos", json={"token": "token-privado", "plataforma": "ANDROID"})
        assert response.status_code == 201 and "token-privado" not in response.text
        saved = db.execute(select(TratamientoDispositivo)).scalar_one()
        assert saved.token_cifrado != "token-privado" and "token-privado" not in saved.token_cifrado
        assert client.delete(f"/api/v1/tratamientos/dispositivos/{saved.id_dispositivo}").status_code == 204
        db.refresh(saved)
        assert saved.activo is False
    finally:
        app.main.app.dependency_overrides.clear()
