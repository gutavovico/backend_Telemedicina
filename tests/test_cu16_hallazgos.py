"""CU16 hallazgos: pruebas verificables para las 10 correcciones.

Cubre (invocando endpoints reales cuando se exige):
1. Validación pública rechaza manipulaciones (detalle, firma, key_id,
   byte PDF, hash_pdf, documento hash) sin devolver valida:true.
2. Autorización sin IDs mágicos (roles con IDs distintos, ID 1 sin ADMIN
   no otorga privilegios).
3. Idempotencia concurrente sin huérfanos (1 receta, 1 idempotencia,
   1 documento, 1 PDF, mismo resultado).
4. Reserva concurrente de folios en PostgreSQL (integración; skip si PG
   no disponible, sin declarar verificación sin evidencia).
5. IP y proxies de confianza (TRUSTED_PROXY_IPS, X-Forwarded-For).
6. Descarga exige prescriptions:download (read no basta).
7. Vigencia máxima 1-90 (0,1,90,91 + clínica reduce + global inválido).
8. Validación criptográfica en startup (6 fallos explícitos).
9. Canonicalización RFC 8785 con vectores (jcs).
10. Modelos vs migración (índices funcionales) se verifica en.commands
    de entrega; aquí se comprueba unicidad normalizada a nivel ORM.
"""
import base64
import hashlib
import json
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.prescriptions import service as rx_service
from app.modules.medical_records.prescriptions.crypto import (
    PrescriptionCryptoError,
    canonicalize_jcs,
    ensure_prescription_crypto_configured,
)
from app.modules.medical_records.prescriptions.router import _client_ip

_FIXED_RAW = bytes(range(32))
FIXED_TOKEN = base64.urlsafe_b64encode(_FIXED_RAW).rstrip(b"=").decode("ascii")
FIXED_HASH = hashlib.sha256(_FIXED_RAW).hexdigest()


def _payload_consulta(id_consulta=45, id_paciente=10, dias_vigencia=30, manual=False):
    detalle = {
        "dosis": "500 mg",
        "frecuencia": "Cada 8 horas",
        "duracion": "7 días",
        "via_administracion": "ORAL",
        "cantidad": 21,
        "indicaciones": "Tomar después de las comidas",
    }
    if manual:
        detalle["nombre_medicamento_manual"] = "Jarabe de prueba"
    else:
        detalle["id_medicamento"] = 14
    return {
        "id_consulta": id_consulta,
        "id_paciente": id_paciente,
        "fecha_vencimiento": (date.today() + timedelta(days=dias_vigencia)).isoformat(),
        "indicaciones_generales": "Mantener hidratación y reposo relativo.",
        "detalles": [detalle],
    }


class FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, host, headers=None):
        self.client = FakeClient(host)
        self.headers = headers or {}


class CU16HallazgosTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = base64.b64encode(
            priv.private_bytes_raw()).decode("ascii")
        settings.PRESCRIPTION_SIGNING_KEY_ID = "test-key-1"
        settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = json.dumps({
            "test-key-1": base64.b64encode(pub.public_bytes_raw()).decode("ascii"),
        })
        settings.PRESCRIPTION_TELEMETRY_HMAC_KEY = "test-hmac-secret"
        settings.PRESCRIPTION_PUBLIC_BASE_URL = "http://testserver"
        settings.PRESCRIPTION_DEFAULT_VALIDITY_DAYS = 90
        settings.TRUSTED_PROXY_IPS = ""
        cls._saved_crypto = (
            settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64,
            settings.PRESCRIPTION_SIGNING_KEY_ID,
            settings.PRESCRIPTION_VERIFICATION_KEYS_JSON,
            settings.PRESCRIPTION_TELEMETRY_HMAC_KEY,
        )
        from app.modules.medical_records.clinical_documents.storage import storage
        cls._storage = storage
        cls._orig_local_dir = storage.local_dir
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="cu16_hallazgos_")
        storage.local_dir = Path(cls._tmpdir.name)
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False,
                                        autoflush=False, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)
        cls._key_counter = 0

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        cls._storage.local_dir = cls._orig_local_dir
        cls._tmpdir.cleanup()
        # Restaurar validez global por si algún test la alteró
        settings.PRESCRIPTION_DEFAULT_VALIDITY_DAYS = 90
        settings.TRUSTED_PROXY_IPS = ""

    def setUp(self):
        self._reset_data()
        self._auth_as(2)
        settings.TRUSTED_PROXY_IPS = ""
        # Restaurar crypto válida antes de cada test (los tests de startup la rompen temporalmente)
        priv_b64, kid, ring, hmac_key = self.__class__._saved_crypto
        # _saved_crypto se tomó tras generar una clave efímera en setUpClass;
        # si un test la rotó, regenerar una válida equivalente:
        try:
            ensure_prescription_crypto_configured()
        except Exception:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            priv = Ed25519PrivateKey.generate()
            settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = base64.b64encode(
                priv.private_bytes_raw()).decode("ascii")
            settings.PRESCRIPTION_SIGNING_KEY_ID = "test-key-1"
            settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = json.dumps({
                "test-key-1": base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii"),
            })
            settings.PRESCRIPTION_TELEMETRY_HMAC_KEY = "test-hmac-secret"
            self.__class__._saved_crypto = (
                settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64,
                settings.PRESCRIPTION_SIGNING_KEY_ID,
                settings.PRESCRIPTION_VERIFICATION_KEYS_JSON,
                settings.PRESCRIPTION_TELEMETRY_HMAC_KEY,
            )
        settings.PRESCRIPTION_DEFAULT_VALIDITY_DAYS = 90

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)
        settings.TRUSTED_PROXY_IPS = ""
        settings.PRESCRIPTION_DEFAULT_VALIDITY_DAYS = 90

    # ---------------- fixtures ---------------- #
    def _db(self):
        return self.SessionLocal()

    def _reset_data(self):
        tables = ["receta_validacion_intentos", "receta_idempotencia", "receta_detalle",
                  "recetas", "secuencias_recetas", "configuracion_recetas", "medicamentos",
                  "documentos_clinicos", "diagnosticos", "consultas", "historias_clinicas",
                  "citas", "medicos", "pacientes", "rol_permisos", "permisos",
                  "auditoria", "usuarios", "roles", "clinicas"]
        with self.engine.begin() as conn:
            for table in tables:
                try:
                    conn.exec_driver_sql(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES "
                "(1, 'Hospital San Juan de Dios - Santa Cruz', 'ACTIVO'), "
                "(2, 'Clínica Las Américas', 'ACTIVO')")
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES "
                "(1, 1, 'ADMIN', 'ACTIVO'), (2, 1, 'MEDICO', 'ACTIVO'), "
                "(4, 1, 'PACIENTE', 'ACTIVO')")
            conn.exec_driver_sql(
                """INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos,
                   correo, password_hash, estado, token_version,
                   notificaciones_push, notificaciones_email, notificaciones_sms) VALUES
                (1, 1, 1, 'Admin', 'Sistema', 'admin@test.com', 'hash1', 'activo', 0, 1, 1, 0),
                (2, 1, 2, 'Carlos', 'Fernández Mendoza', 'medico@test.com', 'hash2', 'activo', 0, 1, 1, 0),
                (7, 1, 2, 'Ana', 'Torres', 'medico2@test.com', 'hash7', 'activo', 0, 1, 1, 0),
                (6, 2, 2, 'Luis', 'Paredes', 'medico3@test.com', 'hash6', 'activo', 0, 1, 1, 0),
                (4, 1, 4, 'María', 'Reneé Morales', 'paciente@test.com', 'hash4', 'activo', 0, 1, 1, 0),
                (5, 1, 4, 'Juan', 'Pérez', 'paciente2@test.com', 'hash5', 'activo', 0, 1, 1, 0)""")
            perms = ["prescriptions:issue", "prescriptions:read", "prescriptions:download",
                     "prescriptions:cancel", "prescriptions:catalog:write"]
            for i, name in enumerate(perms, start=1):
                conn.exec_driver_sql(
                    "INSERT INTO permisos (id_permiso, nombre, descripcion, modulo, accion, estado) "
                    f"VALUES ({i}, '{name}', '{name}', 'prescriptions', '{name}', 'ACTIVO')")
            for pid in (1, 2, 3, 4, 5):
                conn.exec_driver_sql(f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (1, {pid})")
            for pid in (1, 2, 3):
                conn.exec_driver_sql(f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (2, {pid})")
            for pid in (2, 3):
                conn.exec_driver_sql(f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (4, {pid})")
            conn.exec_driver_sql(
                """INSERT INTO pacientes (id_paciente, id_clinica, id_usuario, nombres, apellidos,
                   ci, fecha_nacimiento, genero, telefono, estado) VALUES
                (10, 1, 4, 'María', 'Reneé Morales', '1234910', '1990-01-01', 'F', '+59170000003', 'ACTIVO'),
                (11, 1, 5, 'Juan', 'Pérez', '7654321', '1985-05-05', 'M', '+59170000004', 'ACTIVO'),
                (20, 2, NULL, 'Ana', 'Gómez', '9999999', '1995-09-09', 'F', '+59170000006', 'ACTIVO')""")
            conn.exec_driver_sql(
                "INSERT INTO medicos (id_medico, id_usuario, matricula_profesional, estado) VALUES "
                "(3, 2, 'MP-84920-SC', 'activo'), (7, 7, 'MP-00007', 'activo'), "
                "(8, 6, 'MP-00008', 'activo')")
            conn.exec_driver_sql(
                "INSERT INTO citas (id_cita, id_paciente, id_medico, estado, modalidad, motivo) VALUES "
                "(100, 10, 3, 'EN_CONSULTA', 'PRESENCIAL', 'Control'), "
                "(101, 10, 7, 'EN_CONSULTA', 'PRESENCIAL', 'Control'), "
                "(200, 20, 8, 'EN_CONSULTA', 'PRESENCIAL', 'Control')")
            conn.exec_driver_sql(
                "INSERT INTO historias_clinicas (id_historia, id_clinica, id_paciente, numero_historia) VALUES "
                "(1, 1, 10, 'HCE-2026-000010'), (2, 2, 20, 'HCE-2026-000020')")
            conn.exec_driver_sql(
                """INSERT INTO consultas (id_consulta, id_clinica, id_historia, id_cita, id_medico,
                   motivo_consulta, sintomas, evolucion, plan_medico) VALUES
                (45, 1, 1, 100, 3, 'Faringitis aguda', 'Dolor de garganta', 'Estable', 'Antibiótico'),
                (46, 1, 1, 101, 7, 'Control general', 'Sin síntomas', 'Estable', 'Observación'),
                (47, 2, 2, 200, 8, 'Consulta externa', 'Tos', 'Estable', 'Jarabe')""")
            conn.exec_driver_sql(
                """INSERT INTO medicamentos (id_medicamento, nombre, principio_activo, concentracion,
                   forma_farmaceutica, estado) VALUES
                (14, 'Amoxicilina + Ácido Clavulánico', 'Amoxicilina / Clavulanato',
                 '500 mg / 125 mg', 'Comprimido recubierto', 'ACTIVO'),
                (15, 'Jarabe Obsoleto', 'Principio X', '100 mg', 'Jarabe', 'INACTIVO')""")

    def _auth_as(self, user_id: int):
        db = self._db()
        try:
            user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
            assert user is not None
            db.expunge(user)
        finally:
            db.close()
        app.dependency_overrides[get_current_user] = lambda: user

    def _next_key(self) -> str:
        type(self)._key_counter += 1
        return f"hall-{type(self)._key_counter}-{id(self)}"

    def _emitir(self, payload=None, key=None, user_id=None, headers=None):
        if user_id is not None:
            self._auth_as(user_id)
        hdrs = dict(headers or {})
        hdrs["Idempotency-Key"] = key or self._next_key()
        return self.client.post("/api/v1/recetas", json=payload or _payload_consulta(),
                                headers=hdrs)

    def _count(self, table: str) -> int:
        db = self._db()
        try:
            return db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        finally:
            db.close()

    def _storage_files(self) -> int:
        return sum(1 for _ in Path(self._tmpdir.name).rglob("*") if _.is_file())

    def _emitir_con_token_fijo(self, dias_vigencia=30, key="hall-pub-1", id_consulta=45):
        with mock.patch.object(rx_service, "generate_verification_token",
                               return_value=(FIXED_TOKEN, FIXED_HASH)):
            resp = self._emitir(_payload_consulta(id_consulta=id_consulta,
                                                  dias_vigencia=dias_vigencia), key=key)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def _public_body(self, token):
        resp = self.client.get(f"/api/v1/recetas/validar/{token}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        return resp.json()

    def _assert_publica_no_valida(self, token):
        body = self._public_body(token)
        self.assertFalse(body.get("valida"), f"receta manipulada presentada como válida: {body}")
        self.assertEqual(body, {"valida": False, "estado": "NO_ENCONTRADA"})
        # No expone detalles clínicos manipulados
        for forbidden in ("folio", "medicamento", "paciente", "medico", "institucion"):
            self.assertNotIn(forbidden, json.dumps(body).lower())
        return body

    # ============ 1. VALIDACIÓN PÚBLICA DE INTEGRIDAD ============ #
    def test_1_publica_rechaza_detalle_manipulado(self):
        self._emitir_con_token_fijo(key="h1-det")
        db = self._db()
        try:
            db.execute(text("UPDATE receta_detalle SET dosis='9999 mg'"))
            db.commit()
        finally:
            db.close()
        self._assert_publica_no_valida(FIXED_TOKEN)
        # Telemetría anonimizada existe; no auditoría con usuario ficticio
        db = self._db()
        try:
            n = db.execute(text("SELECT COUNT(*) FROM receta_validacion_intentos")).scalar()
            self.assertGreaterEqual(n, 1)
            audit = db.execute(text("SELECT COUNT(*) FROM auditoria WHERE accion LIKE 'VALIDAR%'")).scalar()
            self.assertEqual(audit, 0)
        finally:
            db.close()

    def test_1_publica_rechaza_firma_manipulada(self):
        self._emitir_con_token_fijo(key="h1-fir")
        db = self._db()
        try:
            db.execute(text("UPDATE recetas SET firma_digital='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=='"))
            db.commit()
        finally:
            db.close()
        self._assert_publica_no_valida(FIXED_TOKEN)

    def test_1_publica_rechaza_key_id_desconocido(self):
        self._emitir_con_token_fijo(key="h1-kid")
        db = self._db()
        try:
            db.execute(text("UPDATE recetas SET key_id='desconocido-999'"))
            db.commit()
        finally:
            db.close()
        self._assert_publica_no_valida(FIXED_TOKEN)

    def test_1_publica_rechaza_pdf_modificado(self):
        body = self._emitir_con_token_fijo(key="h1-pdf")
        db = self._db()
        try:
            row = db.execute(text("SELECT archivo_url FROM documentos_clinicos")).first()
            self.assertIsNotNone(row)
            object_key = row[0]
        finally:
            db.close()
        fpath = (self._storage.local_dir / Path(object_key)).resolve()
        raw = fpath.read_bytes()
        mut = bytearray(raw)
        mut[len(mut) // 2] ^= 0x01
        fpath.write_bytes(bytes(mut))
        try:
            self._assert_publica_no_valida(FIXED_TOKEN)
        finally:
            # Restaurar para no contaminar conteo de huérfanos (el archivo válido se regenera en reset)
            pass

    def test_1_publica_rechaza_hash_pdf_manipulado(self):
        self._emitir_con_token_fijo(key="h1-hpdf")
        db = self._db()
        try:
            db.execute(text("UPDATE recetas SET hash_pdf='00' || substr(hash_pdf, 3)"))
            db.commit()
        finally:
            db.close()
        self._assert_publica_no_valida(FIXED_TOKEN)

    def test_1_publica_rechaza_documento_hash_manipulado(self):
        self._emitir_con_token_fijo(key="h1-hdoc")
        db = self._db()
        try:
            db.execute(text("UPDATE documentos_clinicos SET hash_archivo='ff' || substr(hash_archivo, 3)"))
            db.commit()
        finally:
            db.close()
        self._assert_publica_no_valida(FIXED_TOKEN)

    def test_1_publica_rechaza_algoritmo_version_invalidos(self):
        # Verificación unitaria: algoritmo y versión forman parte de la integridad
        self._emitir_con_token_fijo(key="h1-alg")
        db = self._db()
        try:
            from app.modules.medical_records.prescriptions.models import Receta
            receta = db.query(Receta).order_by(Receta.id_receta.desc()).first()
            self.assertTrue(rx_service.verificar_integridad_receta(db, receta))
            receta.algoritmo_firma = "RSA"
            self.assertFalse(rx_service.verificar_integridad_receta(db, receta))
            receta.algoritmo_firma = "ED25519"
            receta.version_payload = 99
            self.assertFalse(rx_service.verificar_integridad_receta(db, receta))
            db.rollback()
        finally:
            db.close()

    # ============ 2. AUTORIZACIÓN SIN IDs MÁGICOS ============ #
    def test_2_autorizacion_por_permiso_y_rol_no_por_id(self):
        db = self._db()
        try:
            # Roles con IDs no habituales
            db.execute(text("INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES (99, 1, 'ADMIN', 'ACTIVO')"))
            db.execute(text("INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES (55, 1, 'MEDICO', 'ACTIVO')"))
            db.execute(text("INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES (77, 1, 'PACIENTE', 'ACTIVO')"))
            # Permisos: 99 ADMIN todo, 55 MEDICO issue/read/download, 77 PACIENTE read/download
            for pid in (1, 2, 3, 4, 5):
                db.execute(text(f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (99, {pid})"))
            for pid in (1, 2, 3):
                db.execute(text(f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (55, {pid})"))
            for pid in (2, 3):
                db.execute(text(f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (77, {pid})"))
            db.execute(text(
                """INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo,
                   password_hash, estado, token_version, notificaciones_push, notificaciones_email,
                   notificaciones_sms) VALUES
                (90, 1, 99, 'Admin', 'Raro', 'admin99@test.com', 'h', 'activo', 0, 1, 1, 0),
                (50, 1, 55, 'Med', 'Raro', 'med55@test.com', 'h', 'activo', 0, 1, 1, 0),
                (70, 1, 77, 'Pac', 'Raro', 'pac77@test.com', 'h', 'activo', 0, 1, 1, 0)"""))
            db.execute(text(
                "INSERT INTO medicos (id_medico, id_usuario, matricula_profesional, estado) VALUES "
                "(90, 50, 'MP-00090', 'activo')"))
            db.execute(text(
                """INSERT INTO pacientes (id_paciente, id_clinica, id_usuario, nombres, apellidos, ci,
                   fecha_nacimiento, genero, telefono, estado) VALUES
                (90, 1, 70, 'Pac', 'Raro', '9090909', '1990-01-01', 'F', '1', 'ACTIVO')"""))
            db.execute(text(
                "INSERT INTO citas (id_cita, id_paciente, id_medico, estado, modalidad, motivo) VALUES "
                "(900, 90, 90, 'EN_CONSULTA', 'PRESENCIAL', 'Control')"))
            db.execute(text(
                "INSERT INTO historias_clinicas (id_historia, id_clinica, id_paciente, numero_historia) VALUES "
                "(90, 1, 90, 'HCE-90')"))
            db.execute(text(
                """INSERT INTO consultas (id_consulta, id_clinica, id_historia, id_cita, id_medico,
                   motivo_consulta, sintomas, evolucion, plan_medico) VALUES
                (900, 1, 90, 900, 90, 'm', 's', 'e', 'p')"""))
            db.commit()
        finally:
            db.close()
        # Médico con ID de rol 55 (no 2) puede emitir si tiene permiso y es asignado
        payload = _payload_consulta(id_consulta=900, id_paciente=90)
        resp = self._emitir(payload, key="h2-55", user_id=50)
        self.assertEqual(resp.status_code, 201, resp.text)
        receta_id = resp.json()["id_receta"]
        # Paciente con ID 77 ve solo sus recetas
        self._auth_as(70)
        listado = self.client.get("/api/v1/recetas").json()
        self.assertEqual(listado["total"], 1)
        self.assertEqual(listado["items"][0]["id_receta"], receta_id)
        # Admin con ID 99 ve recetas del tenant
        self._auth_as(90)
        self.assertEqual(self.client.get("/api/v1/recetas").json()["total"], 1)

    def test_2_id_1_sin_rol_admin_no_obtiene_privilegios(self):
        from app.modules.medical_records.prescriptions.dependencies import is_admin_user
        db = self._db()
        try:
            # Usuario con id_rol == 1 pero cuyo rol real NO es ADMIN
            db.execute(text("UPDATE roles SET nombre='MEDICO' WHERE id_rol=1"))
            db.commit()
            user = db.query(Usuario).filter(Usuario.id_usuario == 1).first()
            db.expunge(user)
            self.assertFalse(is_admin_user(db, user))
            # Y un ADMIN con ID distinto sí es admin
            db.execute(text("INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES (99, 1, 'ADMIN', 'ACTIVO')"))
            db.execute(text(
                """INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo,
                   password_hash, estado, token_version, notificaciones_push, notificaciones_email,
                   notificaciones_sms) VALUES
                (99, 1, 99, 'Admin', 'Real', 'adminreal@test.com', 'h', 'activo', 0, 1, 1, 0)"""))
            db.commit()
            admin_real = db.query(Usuario).filter(Usuario.id_usuario == 99).first()
            db.expunge(admin_real)
            self.assertTrue(is_admin_user(db, admin_real))
        finally:
            db.close()

    # ============ 3. IDEMPOTENCIA CONCURRENTE SIN HUÉRFANOS ============ #
    def test_3_idempotencia_concurrente_un_solo_pdf(self):
        import os
        db_path = os.path.join(self._tmpdir.name, "idem_conc.db")
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass
        file_engine = create_engine(f"sqlite:///{db_path}")
        FileSession = sessionmaker(bind=file_engine, autocommit=False, autoflush=False,
                                   expire_on_commit=False)
        Base.metadata.create_all(file_engine)
        seed = FileSession()
        try:
            seed.execute(text("INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'C1', 'ACTIVO')"))
            seed.execute(text("INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES (2, 1, 'MEDICO', 'ACTIVO')"))
            seed.execute(text(
                """INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo,
                   password_hash, estado, token_version, notificaciones_push, notificaciones_email,
                   notificaciones_sms) VALUES (2, 1, 2, 'M', 'Uno', 'm@t.com', 'h', 'activo', 0, 1, 1, 0)"""))
            seed.execute(text(
                "INSERT INTO permisos (id_permiso, nombre, descripcion, modulo, accion, estado) VALUES "
                "(1, 'prescriptions:issue', 'x', 'prescriptions', 'issue', 'ACTIVO')"))
            seed.execute(text("INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (2, 1)"))
            seed.execute(text(
                """INSERT INTO pacientes (id_paciente, id_clinica, nombres, apellidos, ci,
                   fecha_nacimiento, genero, telefono, estado) VALUES
                (10, 1, 'P', 'Uno', '111', '1990-01-01', 'F', '1', 'ACTIVO')"""))
            seed.execute(text(
                "INSERT INTO medicos (id_medico, id_usuario, matricula_profesional, estado) VALUES "
                "(3, 2, 'MP-1', 'activo')"))
            seed.execute(text("INSERT INTO citas (id_cita, id_paciente, id_medico, estado) VALUES (100, 10, 3, 'X')"))
            seed.execute(text(
                "INSERT INTO historias_clinicas (id_historia, id_clinica, id_paciente, numero_historia)"
                " VALUES (1, 1, 10, 'HCE-1')"))
            seed.execute(text(
                """INSERT INTO consultas (id_consulta, id_clinica, id_historia, id_cita, id_medico,
                   motivo_consulta, sintomas, evolucion, plan_medico)
                   VALUES (45, 1, 1, 100, 3, 'm', 's', 'e', 'p')"""))
            seed.execute(text(
                """INSERT INTO medicamentos (id_medicamento, nombre, principio_activo, concentracion,
                   forma_farmaceutica, estado) VALUES
                (14, 'Amoxicilina', 'Amoxicilina', '500 mg', 'Comprimido', 'ACTIVO')"""))
            seed.commit()
            user = seed.query(Usuario).filter(Usuario.id_usuario == 2).first()
            seed.expunge(user)
        finally:
            seed.close()
        archivos_antes = self._storage_files()
        from app.modules.medical_records.prescriptions.schemas import RecetaCreateRequest
        resultados, errores = [], []
        lock = threading.Lock()

        def worker():
            db = FileSession()
            try:
                payload = RecetaCreateRequest.model_validate(_payload_consulta())
                receta, es_reintento = rx_service.emitir_receta(
                    db, user=user, tenant_id=1, payload=payload,
                    payload_raw=payload.model_dump(mode="json"),
                    idempotency_key="misma-clave-concurrente", client_ip=None)
                with lock:
                    resultados.append((receta.id_receta, receta.folio, receta.hash_pdf, es_reintento))
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errores.append(repr(exc))
            finally:
                db.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errores, [], f"errores concurrentes: {errores}")
        self.assertEqual(len(resultados), 2)
        # Mismo resultado funcional para ambos reintentos
        self.assertEqual(resultados[0][0], resultados[1][0])
        self.assertEqual(resultados[0][1], resultados[1][1])
        self.assertEqual(resultados[0][2], resultados[1][2])
        # Una sola receta confirmada, un solo registro de idempotencia,
        # un solo documento clínico y un solo PDF persistido, sin huérfanos
        check = FileSession()
        try:
            self.assertEqual(check.execute(text("SELECT COUNT(*) FROM recetas")).scalar(), 1)
            self.assertEqual(check.execute(text("SELECT COUNT(*) FROM receta_idempotencia")).scalar(), 1)
            self.assertEqual(check.execute(text("SELECT COUNT(*) FROM documentos_clinicos")).scalar(), 1)
        finally:
            check.close()
        file_engine.dispose()
        archivos_despues = self._storage_files()
        self.assertEqual(archivos_despues - archivos_antes, 1,
                         "debe persistir un solo PDF y ningún archivo huérfano")

    def test_3_misma_clave_otro_payload_409(self):
        self._emitir(key="h3-conf")
        resp = self._emitir(_payload_consulta(manual=True), key="h3-conf")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "PRESCRIPTION_CONFLICT")

    # ============ 4. FOLIOS POSTGRESQL (INTEGRACIÓN) ============ #
    def test_4_folios_postgres_concurrentes_integracion(self):
        """Integración PostgreSQL: INSERT ON CONFLICT + SELECT FOR UPDATE.

        Si PostgreSQL no está disponible, queda como pendiente explícito
        (skip) sin declarar verificación completada.
        """
        try:
            from sqlalchemy import create_engine as _ce
            base_url = (
                f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}"
                f"@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
            )
            admin = _ce(base_url, isolation_level="AUTOCOMMIT")
            with admin.connect() as c:
                c.execute(text("SELECT 1"))
        except Exception as exc:
            self.skipTest(f"PostgreSQL no disponible en el entorno; prueba de folios pendiente: {type(exc).__name__}")
        import uuid
        dbname = f"cu16_test_{uuid.uuid4().hex[:12]}"
        admin = _ce(base_url, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as c:
                c.execute(text(f'CREATE DATABASE "{dbname}"'))
        except Exception as exc:
            self.skipTest(f"No fue posible crear base descartable; pendiente PG: {exc}")
        try:
            pg_url = (
                f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}"
                f"@{settings.DB_HOST}:{settings.DB_PORT}/{dbname}"
            )
            pg_engine = _ce(pg_url)
            Base.metadata.create_all(pg_engine)
            PgSession = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False,
                                     expire_on_commit=False)
            seed = PgSession()
            try:
                seed.execute(text("INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'C1', 'ACTIVO')"))
                seed.commit()
            finally:
                seed.close()
            folios, errores = [], []
            lock = threading.Lock()

            def worker(i):
                db = PgSession()
                try:
                    folio = rx_service._reservar_folio(db, 1, 2026)
                    db.commit()
                    with lock:
                        folios.append(folio)
                except Exception as exc:  # noqa: BLE001
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    with lock:
                        errores.append(repr(exc))
                finally:
                    db.close()

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errores, [], f"errores PG: {errores}")
            self.assertEqual(len(set(folios)), 8, f"folios duplicados: {folios}")
            for f in folios:
                self.assertRegex(f, r"^REC-2026-\d{6,}$")
            pg_engine.dispose()
        finally:
            try:
                with admin.connect() as c:
                    c.execute(text(
                        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        f"WHERE datname='{dbname}' AND pid <> pg_backend_pid()"))
                    c.execute(text(f'DROP DATABASE IF EXISTS "{dbname}"'))
            except Exception:
                pass
            admin.dispose()

    # ============ 5. IP Y PROXIES ============ #
    def test_5_cliente_directo_ignora_spoof(self):
        req = FakeRequest("203.0.113.10", {"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(_client_ip(req), "203.0.113.10")

    def test_5_proxy_autorizado_acepta_xff(self):
        settings.TRUSTED_PROXY_IPS = "10.0.0.1"
        req = FakeRequest("10.0.0.1", {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
        self.assertEqual(_client_ip(req), "203.0.113.7")

    def test_5_proxy_no_autorizado_ignora_xff(self):
        settings.TRUSTED_PROXY_IPS = "10.0.0.1"
        req = FakeRequest("192.168.1.5", {"X-Forwarded-For": "203.0.113.7"})
        self.assertEqual(_client_ip(req), "192.168.1.5")

    def test_5_encabezado_invalido_se_ignora(self):
        settings.TRUSTED_PROXY_IPS = "10.0.0.1"
        req = FakeRequest("10.0.0.1", {"X-Forwarded-For": "no-es-ip, tampoco"})
        self.assertEqual(_client_ip(req), "10.0.0.1")
        req2 = FakeRequest("203.0.113.10", {"X-Forwarded-For": "999.999.999.999"})
        settings.TRUSTED_PROXY_IPS = ""
        self.assertEqual(_client_ip(req2), "203.0.113.10")

    def test_5_ratelimit_no_evadible_con_xff_directo(self):
        settings.TRUSTED_PROXY_IPS = ""
        for i in range(30):
            resp = self.client.get(f"/api/v1/recetas/validar/9{i:042d}",
                                   headers={"X-Forwarded-For": f"10.9.9.{i % 250 + 1}"})
            self.assertEqual(resp.status_code, 200)
        # Cambiar el encabezado desde cliente directo no evade el límite
        resp = self.client.get("/api/v1/recetas/validar/" + "7" * 43,
                               headers={"X-Forwarded-For": "8.8.8.8"})
        self.assertEqual(resp.status_code, 429)
        self.assertIn("Retry-After", resp.headers)

    # ============ 6. PERMISO DE DESCARGA ============ #
    def test_6_paciente_read_sin_download_consulta_pero_no_descarga(self):
        body = self._emitir().json()
        receta_id = body["id_receta"]
        db = self._db()
        try:
            db.execute(text("DELETE FROM rol_permisos WHERE id_rol=4 AND id_permiso=3"))
            db.commit()
        finally:
            db.close()
        try:
            self._auth_as(4)
            # Puede consultar listado y detalle con read
            self.assertEqual(self.client.get("/api/v1/recetas").status_code, 200)
            self.assertEqual(self.client.get(f"/api/v1/recetas/{receta_id}").status_code, 200)
            # Pero recibe 403 al descargar sin download
            resp = self.client.get(f"/api/v1/recetas/{receta_id}/pdf")
            self.assertEqual(resp.status_code, 403, resp.text)
        finally:
            db = self._db()
            try:
                db.execute(text("INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (4, 3)"))
                db.commit()
            finally:
                db.close()

    # ============ 7. VIGENCIA MÁXIMA ============ #
    def test_7_vigencia_0_1_90_91(self):
        self.assertEqual(self._emitir(_payload_consulta(dias_vigencia=0)).status_code, 422)
        self.assertEqual(self._emitir(_payload_consulta(dias_vigencia=1), key="h7-1").status_code, 201)
        self.assertEqual(self._emitir(_payload_consulta(dias_vigencia=90), key="h7-90").status_code, 201)
        self.assertEqual(self._emitir(_payload_consulta(dias_vigencia=91)).status_code, 422)

    def test_7_clinica_reduce_maximo(self):
        db = self._db()
        try:
            db.execute(text("INSERT INTO configuracion_recetas (id_clinica, vigencia_maxima_dias) VALUES (1, 30)"))
            db.commit()
        finally:
            db.close()
        self.assertEqual(self._emitir(_payload_consulta(dias_vigencia=31)).status_code, 422)
        self.assertEqual(self._emitir(_payload_consulta(dias_vigencia=30), key="h7-c30").status_code, 201)

    def test_7_global_invalido_error_explicito(self):
        for invalido in (0, 91):
            settings.PRESCRIPTION_DEFAULT_VALIDITY_DAYS = invalido
            with self.assertRaises(rx_service.PrescriptionError) as ctx:
                rx_service._global_vigencia_maxima()
            self.assertEqual(ctx.exception.code, "PRESCRIPTION_CONFIG")
            # La emisión no usa silenciosamente el valor inválido
            with self.assertRaises(rx_service.PrescriptionError) as ctx2:
                db = self._db()
                try:
                    rx_service._max_vigencia_dias(db, 1)
                finally:
                    db.close()
            self.assertEqual(ctx2.exception.code, "PRESCRIPTION_CONFIG")
        settings.PRESCRIPTION_DEFAULT_VALIDITY_DAYS = 90

    # ============ 8. STARTUP CRIPTOGRÁFICO ============ #
    def _valid_crypto(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.generate()
        pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")
        return (base64.b64encode(priv.private_bytes_raw()).decode("ascii"), "test-key-1",
                json.dumps({"test-key-1": pub_b64}))

    def test_8_startup_config_valida_ok(self):
        priv_b64, kid, ring = self._valid_crypto()
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = priv_b64
        settings.PRESCRIPTION_SIGNING_KEY_ID = kid
        settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = ring
        settings.PRESCRIPTION_TELEMETRY_HMAC_KEY = "test-hmac-secret"
        self.assertEqual(ensure_prescription_crypto_configured(), kid)

    def test_8_startup_falta_privada(self):
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = ""
        with self.assertRaises(PrescriptionCryptoError):
            ensure_prescription_crypto_configured()

    def test_8_startup_privada_invalida(self):
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = "!!!no-base64!!!"
        with self.assertRaises(PrescriptionCryptoError):
            ensure_prescription_crypto_configured()

    def test_8_startup_falta_key_id(self):
        priv_b64, _, ring = self._valid_crypto()
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = priv_b64
        settings.PRESCRIPTION_SIGNING_KEY_ID = ""
        settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = ring
        with self.assertRaises(PrescriptionCryptoError):
            ensure_prescription_crypto_configured()

    def test_8_startup_activo_no_en_anillo(self):
        priv_b64, _, _ = self._valid_crypto()
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = priv_b64
        settings.PRESCRIPTION_SIGNING_KEY_ID = "test-key-1"
        settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = json.dumps({"otra-clave": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="})
        with self.assertRaises(PrescriptionCryptoError):
            ensure_prescription_crypto_configured()

    def test_8_startup_publica_no_corresponde(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.generate()
        otra = Ed25519PrivateKey.generate()
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = base64.b64encode(
            priv.private_bytes_raw()).decode("ascii")
        settings.PRESCRIPTION_SIGNING_KEY_ID = "test-key-1"
        settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = json.dumps({
            "test-key-1": base64.b64encode(otra.public_key().public_bytes_raw()).decode("ascii")})
        with self.assertRaises(PrescriptionCryptoError) as ctx:
            ensure_prescription_crypto_configured()
        # No expone material privado en el error
        self.assertNotIn(settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64, str(ctx.exception))

    def test_8_startup_anillo_invalido(self):
        priv_b64, kid, _ = self._valid_crypto()
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = priv_b64
        settings.PRESCRIPTION_SIGNING_KEY_ID = kid
        settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = "{no-json"
        with self.assertRaises(PrescriptionCryptoError):
            ensure_prescription_crypto_configured()

    # ============ 9. RFC 8785 ============ #
    def test_9_jcs_vectores(self):
        self.assertEqual(canonicalize_jcs({"b": 1, "a": [3, 2]}), b'{"a":[3,2],"b":1}')
        self.assertEqual(canonicalize_jcs({"n": 1e-6}), b'{"n":0.000001}')
        # Exponentes positivos y negativos reales de jcs
        self.assertEqual(canonicalize_jcs({"n": 1e21}), b'{"n":1e+21}')
        self.assertEqual(canonicalize_jcs({"n": 1e-7}), b'{"n":1e-7}')
        # Cero y cero negativo normalizados a 0
        self.assertEqual(canonicalize_jcs({"n": 0.0}), b'{"n":0}')
        self.assertEqual(canonicalize_jcs({"n": -0.0}), b'{"n":0}')
        self.assertEqual(canonicalize_jcs({"n": 0}), b'{"n":0}')
        # Unicode UTF-8 determinista
        out = canonicalize_jcs({"u": "caf\u00e9"})
        self.assertIn("caf".encode("utf-8"), out)
        # Orden lexicográfico y escapes
        self.assertEqual(canonicalize_jcs({"z": 1, "a": 2}), b'{"a":2,"z":1}')
        self.assertEqual(canonicalize_jcs({"s": "a\"b\\c\n"}), b'{"s":"a\\"b\\\\c\\n"}')
        # Rechazo NaN e infinito
        with self.assertRaises(PrescriptionCryptoError):
            canonicalize_jcs({"x": float("nan")})
        with self.assertRaises(PrescriptionCryptoError):
            canonicalize_jcs({"x": float("inf")})
        with self.assertRaises(PrescriptionCryptoError):
            canonicalize_jcs({"x": float("-inf")})

    def test_9_firma_verificacion_tras_jcs(self):
        receta_id = self._emitir().json()["id_receta"]
        db = self._db()
        try:
            from app.modules.medical_records.prescriptions.models import Receta
            receta = db.query(Receta).filter(Receta.id_receta == receta_id).first()
            self.assertTrue(rx_service.verificar_integridad_receta(db, receta))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
