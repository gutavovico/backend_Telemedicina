"""Pruebas unitarias y de integración para CU20: Notificaciones y Recordatorios Multicanal."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.communications.notificaciones.adapters import DeliveryResult
from app.modules.communications.notificaciones.crypto_webpush import (
    cifrar_payload_webpush,
    es_url_segura_webpush,
    generar_cabecera_vapid,
    generar_par_vapid,
)
from app.modules.communications.notificaciones.models import (
    DispositivoAutorizado,
    EventoOutbox,
    Notificacion,
)
from app.modules.communications.notificaciones.schemas import (
    PreferenciasNotificacionUpdateDTO,
    RegistroDispositivoDTO,
)
from app.modules.communications.notificaciones.service import (
    NotificacionService,
    resolver_canal_badge,
    resolver_categoria,
    resolver_enlace_accion,
)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Clinica.__table__,
        Rol.__table__,
        Usuario.__table__,
        DispositivoAutorizado.__table__,
        EventoOutbox.__table__,
        Notificacion.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionTesting()
    try:
        clinica_a = Clinica(id_clinica=1, nombre="Hospital San Juan de Dios", estado="ACTIVO")
        clinica_b = Clinica(id_clinica=2, nombre="Clínica Norte", estado="ACTIVO")
        rol_pac = Rol(id_rol=1, id_clinica=1, nombre="PACIENTE", estado="ACTIVO")
        rol_med = Rol(id_rol=2, id_clinica=1, nombre="MEDICO", estado="ACTIVO")
        rol_adm = Rol(id_rol=3, id_clinica=1, nombre="ADMIN", estado="ACTIVO")
        session.add_all([clinica_a, clinica_b, rol_pac, rol_med, rol_adm])
        session.flush()

        paciente = Usuario(
            id_usuario=10,
            id_clinica=1,
            id_rol=1,
            nombres="Ana",
            apellidos="Gutiérrez",
            correo="ana@test.com",
            telefono="+59170000010",
            password_hash="hash",
            estado="ACTIVO",
            notificaciones_push=True,
            notificaciones_email=True,
            notificaciones_sms=True,
        )
        medico = Usuario(
            id_usuario=20,
            id_clinica=1,
            id_rol=2,
            nombres="Lucía",
            apellidos="Rojas",
            correo="lucia@test.com",
            telefono="+59170000020",
            password_hash="hash",
            estado="ACTIVO",
            notificaciones_push=True,
            notificaciones_email=True,
            notificaciones_sms=False,
        )
        otro_tenant = Usuario(
            id_usuario=30,
            id_clinica=2,
            id_rol=1,
            nombres="Carlos",
            apellidos="Mendez",
            correo="carlos@test.com",
            password_hash="hash",
            estado="ACTIVO",
        )
        session.add_all([paciente, medico, otro_tenant])
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


class FakeAdapter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def enviar(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


# ------------------------------------------------------------------ #
# 1. Criptografía Web Push (RFC 8291 + RFC 8292 + SSRF)
# ------------------------------------------------------------------ #

def test_crypto_webpush_cifrado_vapid_y_ssrf():
    pub_vapid, priv_vapid = generar_par_vapid()
    assert len(pub_vapid) > 40
    assert "BEGIN PRIVATE KEY" in priv_vapid

    header = generar_cabecera_vapid(
        "https://fcm.googleapis.com/fcm/send/abc",
        priv_vapid,
        pub_vapid,
        "mailto:soporte@telemedicina.com",
    )
    assert header.startswith("vapid t=")
    assert f", k={pub_vapid}" in header

    # Claves simuladas del cliente del navegador
    client_priv = ec.generate_private_key(ec.SECP256R1())
    client_pub = client_priv.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    p256dh_b64 = base64.urlsafe_b64encode(client_pub).decode().rstrip("=")
    auth_b64 = base64.urlsafe_b64encode(b"0123456789abcdef").decode().rstrip("=")

    encrypted, enc_headers = cifrar_payload_webpush(b'{"title":"Hola"}', p256dh_b64, auth_b64)
    assert len(encrypted) > 86
    assert enc_headers["Content-Encoding"] == "aes128gcm"

    # Validación SSRF
    assert es_url_segura_webpush("https://fcm.googleapis.com/fcm/send/xyz") is True
    assert es_url_segura_webpush("http://fcm.googleapis.com/fcm/send/xyz") is False
    assert es_url_segura_webpush("https://localhost/push") is False
    assert es_url_segura_webpush("https://127.0.0.1/push") is False
    assert es_url_segura_webpush("https://169.254.169.254/latest/meta-data") is False
    assert es_url_segura_webpush("https://10.0.0.5/push") is False


# ------------------------------------------------------------------ #
# 2. Enrutamiento por Rol y Badges (SMS / WhatsApp / Push / Correo)
# ------------------------------------------------------------------ #

def test_enrutamiento_por_rol_y_badges():
    assert resolver_categoria("SALA_VIRTUAL_ABIERTA") == "CITAS"
    assert resolver_categoria("DOCUMENTO_DISPONIBLE") == "DOCUMENTOS"
    assert resolver_categoria("MEDICACION_TRATAMIENTO") == "DOCUMENTOS"
    assert resolver_categoria("ALERTA_SISTEMA") == "SISTEMA"

    assert resolver_enlace_accion("PACIENTE", "SALA_VIRTUAL_ABIERTA", "SALA_VIRTUAL", "42") == "/citas/42/teleconsulta"
    assert resolver_enlace_accion("MEDICO", "PACIENTE_EN_ESPERA", "SALA_VIRTUAL", "42") == "/admin/teleconsulta/42"
    assert resolver_enlace_accion("MEDICO", "NUEVA_CITA_AGENDADA", "CITA", "99") == "/admin/consultas"
    assert resolver_enlace_accion("ADMIN", "BACKUP", "BACKUP", None) == "/admin/backups"

    assert resolver_canal_badge("SMS", None, {"proveedor": "whatsapp"}) == "WhatsApp"
    assert resolver_canal_badge("SMS", None, {}) == "SMS"
    assert resolver_canal_badge("EMAIL") == "Correo"
    assert resolver_canal_badge("PUSH") == "Push"


# ------------------------------------------------------------------ #
# 3. Registro/Revocación de Dispositivos y Deduplicación Outbox
# ------------------------------------------------------------------ #

def test_dispositivos_y_deduplicacion_idempotente(db_session):
    srv = NotificacionService(db_session)
    paciente = db_session.execute(select(Usuario).where(Usuario.id_usuario == 10)).scalar_one()

    disp_id = str(uuid.uuid4())
    d1 = srv.registrar_dispositivo(
        paciente,
        RegistroDispositivoDTO(dispositivo_id=disp_id, canal="FLUTTER", push_token="fcm_token_1"),
    )
    assert d1.estado == "ACTIVO"
    assert d1.revision == 1

    # Re-registro actualiza token e incrementa revisión
    d2 = srv.registrar_dispositivo(
        paciente,
        RegistroDispositivoDTO(dispositivo_id=disp_id, canal="FLUTTER", push_token="fcm_token_2"),
    )
    assert d2.id_dispositivo == d1.id_dispositivo
    assert d2.revision == 2

    # Control de duplicados (idempotencia)
    n1 = srv.emitir_notificacion(
        id_usuario=10,
        tipo="SALA_VIRTUAL_ABIERTA",
        titulo="La Dra. Rojas abrió la sala",
        mensaje="Tu teleconsulta de las 10:30 está lista.",
        recurso_tipo="SALA_VIRTUAL",
        recurso_id="101",
        idempotency_key="sala-101-abierta",
    )
    n2 = srv.emitir_notificacion(
        id_usuario=10,
        tipo="SALA_VIRTUAL_ABIERTA",
        titulo="La Dra. Rojas abrió la sala",
        mensaje="Tu teleconsulta de las 10:30 está lista.",
        recurso_tipo="SALA_VIRTUAL",
        recurso_id="101",
        idempotency_key="sala-101-abierta",
    )
    db_session.commit()

    assert n1.id_notificacion == n2.id_notificacion
    outbox_rows = db_session.execute(select(EventoOutbox)).scalars().all()
    assert len(outbox_rows) == 1

    # Revocación
    revocados = srv.revocar_dispositivo(10, disp_id)
    db_session.commit()
    assert revocados == 1
    assert len(srv.listar_dispositivos(10)) == 0


# ------------------------------------------------------------------ #
# 4. Despacho Multicanal, Reintentos sin Duplicados y Revocación 410
# ------------------------------------------------------------------ #

def test_worker_outbox_multicanal_reintentos_y_revocacion_token(db_session):
    paciente = db_session.execute(select(Usuario).where(Usuario.id_usuario == 10)).scalar_one()

    wp_fake = FakeAdapter([DeliveryResult(exito=False, codigo="TOKEN_INVALIDO", token_invalido=True, detalle="HTTP 410")])
    fcm_fake = FakeAdapter([DeliveryResult(exito=True, codigo="ACEPTADO", mensaje_id="fcm_1")])
    email_fake = FakeAdapter([
        DeliveryResult(exito=False, codigo="TIMEOUT", reintentable=True, detalle="SMTP timeout"),
        DeliveryResult(exito=True, codigo="ACEPTADO", mensaje_id="mail_2"),
    ])
    sms_fake = FakeAdapter([DeliveryResult(exito=True, codigo="ACEPTADO", mensaje_id="sms_1")])

    srv = NotificacionService(
        db_session,
        adapter_webpush=wp_fake,
        adapter_fcm=fcm_fake,
        adapter_email=email_fake,
        adapter_sms=sms_fake,
    )

    sub_json = json.dumps({"endpoint": "https://push.example/1", "keys": {"p256dh": "x" * 20, "auth": "y" * 16}})
    srv.registrar_dispositivo(paciente, RegistroDispositivoDTO(dispositivo_id="web-1", canal="PWA", push_token=sub_json))
    srv.registrar_dispositivo(paciente, RegistroDispositivoDTO(dispositivo_id="mob-1", canal="FLUTTER", push_token="fcm_ok"))

    srv.emitir_notificacion(
        id_usuario=10,
        tipo="RECORDATORIO_CITA",
        titulo="Recordatorio de cita",
        mensaje="Mañana 10:30 con la Dra. Lucía Rojas",
        canal_objetivo="MULTI",
        recurso_tipo="CITA",
        recurso_id="55",
    )
    db_session.commit()

    # Intento 1: WebPush devuelve 410 (se revoca), FCM OK, SMS OK, Email TIMEOUT -> REINTENTO
    res1 = srv.procesar_outbox(limite=10)
    db_session.commit()
    assert res1["procesados"] == 1
    assert res1["reintentos"] == 1
    assert len(fcm_fake.calls) == 1
    assert len(sms_fake.calls) == 1
    assert len(email_fake.calls) == 1

    # El dispositivo WebPush con 410 debe quedar REVOCADO automáticamente
    web_disp = db_session.execute(
        select(DispositivoAutorizado).where(DispositivoAutorizado.dispositivo_id == "web-1")
    ).scalar_one()
    assert web_disp.estado == "REVOCADO"

    # Forzar ventana de reintento vencida
    ev = db_session.execute(select(EventoOutbox)).scalar_one()
    ev.proximo_intento_en = datetime.now(timezone.utc) - timedelta(seconds=5)
    db_session.commit()

    # Intento 2: solo reintenta Email; NO reenvía FCM ni SMS (control de duplicados por destino)
    res2 = srv.procesar_outbox(limite=10)
    db_session.commit()
    assert res2["enviados"] == 1
    assert len(fcm_fake.calls) == 1  # No se reenvió
    assert len(sms_fake.calls) == 1  # No se reenvió
    assert len(email_fake.calls) == 2  # Sí se reintentó y tuvo éxito


# ------------------------------------------------------------------ #
# 5. Aislamiento por Rol/Tenant, Lectura y Endpoints REST
# ------------------------------------------------------------------ #

def test_bandeja_aislamiento_y_endpoints_rest(db_session):
    srv = NotificacionService(db_session)
    n_pac = srv.emitir_notificacion(
        id_usuario=10,
        tipo="DOCUMENTO_DISPONIBLE",
        titulo="Nuevo resultado disponible",
        mensaje="Hemograma completo · Laboratorio central",
        canal_objetivo="EMAIL",
        recurso_tipo="DOCUMENTO",
        recurso_id="77",
    )
    n_med = srv.emitir_notificacion(
        id_usuario=20,
        tipo="PACIENTE_EN_ESPERA",
        titulo="Paciente esperando en sala",
        mensaje="Ana Gutiérrez ingresó a la sala virtual.",
        canal_objetivo="PUSH",
        recurso_tipo="SALA_VIRTUAL",
        recurso_id="88",
    )
    db_session.commit()

    # El paciente NO puede marcar como leída la notificación del médico (404 aislamiento)
    with pytest.raises(HTTPException) as exc:
        srv.marcar_leida(id_usuario=10, id_notificacion=n_med.id_notificacion, id_clinica=1)
    assert exc.value.status_code == 404

    # TestClient con paciente autenticado
    paciente = db_session.execute(select(Usuario).where(Usuario.id_usuario == 10)).scalar_one()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: paciente
    app.dependency_overrides[get_current_tenant_id] = lambda: 1
    try:
        client = TestClient(app)

        r_resumen = client.get("/api/v1/notificaciones/resumen-no-leidas")
        assert r_resumen.status_code == 200
        assert r_resumen.json()["no_leidas"] == 1

        r_bandeja = client.get("/api/v1/notificaciones/bandeja?categoria=DOCUMENTOS")
        assert r_bandeja.status_code == 200
        items = r_bandeja.json()
        assert len(items) == 1
        assert items[0]["titulo"] == "Nuevo resultado disponible"
        assert items[0]["canal_badge"] == "Correo"
        assert items[0]["enlace_accion"] == "/mis-documentos/77"

        r_leer = client.patch(f"/api/v1/notificaciones/bandeja/{n_pac.id_notificacion}/leer")
        assert r_leer.status_code == 200
        assert r_leer.json()["estado"] == "LEIDA"

        r_resumen2 = client.get("/api/v1/notificaciones/resumen-no-leidas")
        assert r_resumen2.json()["no_leidas"] == 0

        # Preferencias
        r_pref = client.put("/api/v1/notificaciones/preferencias", json={"notificaciones_sms": False})
        assert r_pref.status_code == 200
        assert r_pref.json()["notificaciones_sms"] is False
    finally:
        app.dependency_overrides.clear()
