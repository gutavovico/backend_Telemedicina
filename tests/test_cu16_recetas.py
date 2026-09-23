"""CU16 - Emitir y Validar Recetas Médicas Digitales.

Cubre todos los escenarios Gherkin de
specs/openspec/changes/cu16-recetas-digitales/specs/prescriptions/spec.md
más firma, hash, concurrencia, idempotencia, rollback, anulación,
sustitución, validación pública, rate limiting y telemetría anonimizada.
"""
import base64
import hashlib
import hmac
import json
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.prescriptions import service as rx_service
from app.modules.medical_records.prescriptions.crypto import (
    canonicalize_jcs,
    mask_document,
    mask_patient_name,
)

# Token determinista para pruebas de validación pública (32 bytes fijos)
_FIXED_RAW = bytes(range(32))
FIXED_TOKEN = base64.urlsafe_b64encode(_FIXED_RAW).rstrip(b"=").decode("ascii")
FIXED_HASH = hashlib.sha256(_FIXED_RAW).hexdigest()


def _payload_consulta(id_consulta=45, id_paciente=10, dias_vigencia=30, manual=False,
                      ambos=False, ninguno=False, inactivo=False):
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
    elif ambos:
        detalle["id_medicamento"] = 14
        detalle["nombre_medicamento_manual"] = "Jarabe de prueba"
    elif ninguno:
        pass
    elif inactivo:
        detalle["id_medicamento"] = 15
    else:
        detalle["id_medicamento"] = 14
    return {
        "id_consulta": id_consulta,
        "id_paciente": id_paciente,
        "fecha_vencimiento": (date.today() + timedelta(days=dias_vigencia)).isoformat(),
        "indicaciones_generales": "Mantener hidratación y reposo relativo.",
        "detalles": [detalle],
    }


class CU16RecetasTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Claves Ed25519 de prueba (nunca reales ni versionadas con secretos)
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

        # Almacenamiento aislado por suite
        from app.modules.medical_records.clinical_documents.storage import storage
        cls._storage = storage
        cls._orig_local_dir = storage.local_dir
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="cu16_storage_")
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

    # ---------------- fixtures ---------------- #

    def setUp(self):
        self._reset_data()
        self._auth_as(2)  # médico 1 por defecto

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

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
                conn.exec_driver_sql(
                    f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (1, {pid})")
            for pid in (1, 2, 3):
                conn.exec_driver_sql(
                    f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (2, {pid})")
            for pid in (2, 3):
                conn.exec_driver_sql(
                    f"INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (4, {pid})")
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
        return f"key-{type(self)._key_counter}-{id(self)}"

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
            return db.execute(__import__("sqlalchemy").text(f"SELECT COUNT(*) FROM {table}")).scalar()
        finally:
            db.close()

    def _storage_files(self) -> int:
        return sum(1 for _ in Path(self._tmpdir.name).rglob("*") if _.is_file())

    # ---------------- emisión exitosa ---------------- #

    def test_emision_exitosa(self):
        resp = self._emitir()
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["folio"], f"REC-{date.today().year}-000001")
        self.assertEqual(body["estado"], "EMITIDA")
        self.assertFalse(body["esta_vencida"])
        self.assertEqual(body["pdf_url"], f"/api/v1/recetas/{body['id_receta']}/pdf")
        self.assertEqual(body["algoritmo_firma"], "ED25519")
        self.assertEqual(len(body["detalles"]), 1)
        det = body["detalles"][0]
        self.assertEqual(det["medicamento_nombre"], "Amoxicilina + Ácido Clavulánico")
        self.assertEqual(det["principio_activo"], "Amoxicilina / Clavulanato")
        self.assertEqual(det["posicion"], 1)
        # Documento clínico RECETA con hash idéntico
        db = self._db()
        try:
            doc = db.execute(__import__("sqlalchemy").text(
                "SELECT tipo_documento, estado, hash_archivo, archivo_url FROM documentos_clinicos"
            )).first()
            self.assertIsNotNone(doc)
            self.assertEqual(doc[0], "RECETA")
            self.assertEqual(doc[1], "ACTIVO")
            self.assertEqual(doc[2], body["hash_pdf"])
            auditoria = db.execute(__import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM auditoria WHERE tabla_afectada='recetas' AND accion='EMITIR_RECETA'"
            )).scalar()
            self.assertEqual(auditoria, 1)
        finally:
            db.close()

    def test_consulta_otra_clinica_404(self):
        resp = self._emitir(_payload_consulta(id_consulta=47))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self._count("recetas"), 0)
        self.assertEqual(self._count("documentos_clinicos"), 0)
        self.assertEqual(self._count("auditoria"), 0)

    def test_medico_no_asignado_403(self):
        resp = self._emitir(_payload_consulta(id_consulta=46), user_id=2)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._count("recetas"), 0)

    def test_paciente_inconsistente_422(self):
        resp = self._emitir(_payload_consulta(id_consulta=45, id_paciente=11))
        self.assertEqual(resp.status_code, 422)

    def test_sin_idempotency_key_422(self):
        resp = self.client.post("/api/v1/recetas", json=_payload_consulta())
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(body["code"], "PRESCRIPTION_VALIDATION")

    # ---------------- catálogo / XOR ---------------- #

    def test_medicamento_manual_ok(self):
        resp = self._emitir(_payload_consulta(manual=True))
        self.assertEqual(resp.status_code, 201, resp.text)
        det = resp.json()["detalles"][0]
        self.assertIsNone(det["id_medicamento"])
        self.assertEqual(det["medicamento_nombre"], "Jarabe de prueba")

    def test_xor_ambos_422(self):
        resp = self._emitir(_payload_consulta(ambos=True))
        self.assertEqual(resp.status_code, 422)

    def test_xor_ninguno_422(self):
        resp = self._emitir(_payload_consulta(ninguno=True))
        self.assertEqual(resp.status_code, 422)

    def test_medicamento_inactivo_422(self):
        resp = self._emitir(_payload_consulta(inactivo=True))
        self.assertEqual(resp.status_code, 422)

    def test_medicamento_inexistente_404(self):
        payload = _payload_consulta()
        payload["detalles"][0]["id_medicamento"] = 999
        resp = self._emitir(payload)
        self.assertEqual(resp.status_code, 404)

    def test_medico_no_crea_medicamento_403(self):
        resp = self.client.post("/api/v1/medicamentos", json={"nombre": "Prueba X"})
        self.assertEqual(resp.status_code, 403)

    def test_admin_crea_medicamento_201_y_duplicado_409(self):
        self._auth_as(1)
        resp = self.client.post("/api/v1/medicamentos", json={
            "nombre": "Ibuprofeno", "principio_activo": "Ibuprofeno",
            "concentracion": "400 mg", "forma_farmaceutica": "Comprimido"})
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()["estado"], "ACTIVO")
        dup = self.client.post("/api/v1/medicamentos", json={
            "nombre": "  ibuprofeno ", "concentracion": "400 MG",
            "forma_farmaceutica": "comprimido"})
        self.assertEqual(dup.status_code, 409)

    def test_buscar_medicamentos_medico(self):
        resp = self.client.get("/api/v1/medicamentos", params={"query": "amoxi"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["nombre"], "Amoxicilina + Ácido Clavulánico")

    # ---------------- vigencia ---------------- #

    def test_vigencia_fuera_de_intervalo_422(self):
        payload = _payload_consulta(dias_vigencia=0)
        self.assertEqual(self._emitir(payload).status_code, 422)
        payload = _payload_consulta(dias_vigencia=91)
        self.assertEqual(self._emitir(payload).status_code, 422)
        payload = _payload_consulta(dias_vigencia=1)
        self.assertEqual(self._emitir(payload, key="vig-1").status_code, 201)

    def test_configuracion_clinica_reduce_maximo(self):
        db = self._db()
        try:
            db.execute(__import__("sqlalchemy").text(
                "INSERT INTO configuracion_recetas (id_clinica, vigencia_maxima_dias) VALUES (1, 30)"))
            db.commit()
        finally:
            db.close()
        self.assertEqual(self._emitir(_payload_consulta(dias_vigencia=31)).status_code, 422)
        self.assertEqual(self._emitir(_payload_consulta(dias_vigencia=30), key="c30").status_code, 201)

    # ---------------- snapshots ---------------- #

    def test_snapshot_inmutable_ante_cambio_catalogo(self):
        receta_id = self._emitir().json()["id_receta"]
        db = self._db()
        try:
            db.execute(__import__("sqlalchemy").text(
                "UPDATE medicamentos SET nombre='OTRO NOMBRE' WHERE id_medicamento=14"))
            db.commit()
        finally:
            db.close()
        detail = self.client.get(f"/api/v1/recetas/{receta_id}").json()
        self.assertEqual(detail["detalles"][0]["medicamento_nombre"],
                         "Amoxicilina + Ácido Clavulánico")

    # ---------------- firma e integridad ---------------- #

    def test_firma_valida_y_hash_pdf(self):
        receta_id = self._emitir().json()["id_receta"]
        db = self._db()
        try:
            from app.modules.medical_records.prescriptions.models import Receta
            receta = db.query(Receta).filter(Receta.id_receta == receta_id).first()
            self.assertTrue(rx_service.verificar_integridad_receta(db, receta))
            self.assertTrue(rx_service.verify_canonical_signature(
                receta.key_id,
                rx_service.canonicalize_jcs(rx_service._build_canonical_dict(
                    receta=receta,
                    detalles=db.query(rx_service.RecetaDetalle).filter(
                        rx_service.RecetaDetalle.id_receta == receta_id).all(),
                    matricula="MP-84920-SC",
                    fecha_emision_iso=rx_service._fecha_emision_iso(receta.fecha_emision))),
                receta.firma_digital))
        finally:
            db.close()

    def test_manipulacion_detalle_invalida_firma(self):
        receta_id = self._emitir().json()["id_receta"]
        db = self._db()
        try:
            from app.modules.medical_records.prescriptions.models import Receta
            db.execute(__import__("sqlalchemy").text(
                "UPDATE receta_detalle SET dosis='9999 mg' WHERE id_receta=:rid"),
                {"rid": receta_id})
            receta = db.query(Receta).filter(Receta.id_receta == receta_id).first()
            self.assertFalse(rx_service.verificar_integridad_receta(db, receta))
            db.rollback()
        finally:
            db.close()

    def test_rotacion_key_id_historica(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        receta_id = self._emitir().json()["id_receta"]
        # Rotar la clave activa conservando la histórica en el anillo
        nueva = Ed25519PrivateKey.generate()
        nueva_pub = base64.b64encode(nueva.public_key().public_bytes_raw()).decode("ascii")
        vieja_pub = json.loads(settings.PRESCRIPTION_VERIFICATION_KEYS_JSON)["test-key-1"]
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = base64.b64encode(
            nueva.private_bytes_raw()).decode("ascii")
        settings.PRESCRIPTION_SIGNING_KEY_ID = "test-key-2"
        settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = json.dumps(
            {"test-key-1": vieja_pub, "test-key-2": nueva_pub})
        try:
            db = self._db()
            try:
                from app.modules.medical_records.prescriptions.models import Receta
                receta = db.query(Receta).filter(Receta.id_receta == receta_id).first()
                self.assertTrue(rx_service.verificar_integridad_receta(db, receta))
            finally:
                db.close()
            # La nueva emisión usa el nuevo key_id
            resp = self._emitir(_payload_consulta(id_consulta=46, dias_vigencia=10),
                                key="rot-1", user_id=7)
            self.assertEqual(resp.status_code, 201, resp.text)
            self.assertEqual(resp.json()["key_id"], "test-key-2")
        finally:
            self._reset_crypto_key()

    def _reset_crypto_key(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.generate()
        settings.PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64 = base64.b64encode(
            priv.private_bytes_raw()).decode("ascii")
        settings.PRESCRIPTION_SIGNING_KEY_ID = "test-key-1"
        settings.PRESCRIPTION_VERIFICATION_KEYS_JSON = json.dumps({
            "test-key-1": base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii"),
        })

    def test_descarga_pdf_y_hash(self):
        body = self._emitir().json()
        resp = self.client.get(f"/api/v1/recetas/{body['id_receta']}/pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/pdf", resp.headers["content-type"])
        self.assertTrue(resp.content.startswith(b"%PDF-1.4"))
        self.assertEqual(hashlib.sha256(resp.content).hexdigest(), body["hash_pdf"])
        self.assertIn(b"/api/v1/recetas/validar/", resp.content)

    # ---------------- roles y aislamiento ---------------- #

    def test_paciente_solo_sus_recetas(self):
        receta_id = self._emitir().json()["id_receta"]
        self._auth_as(4)
        listado = self.client.get("/api/v1/recetas").json()
        self.assertEqual(listado["total"], 1)
        self.assertEqual(listado["items"][0]["id_receta"], receta_id)
        self.assertEqual(self.client.get(f"/api/v1/recetas/{receta_id}").status_code, 200)

    def test_paciente_ajeno_404(self):
        receta_id = self._emitir().json()["id_receta"]
        self._auth_as(5)
        self.assertEqual(self.client.get("/api/v1/recetas").json()["total"], 0)
        self.assertEqual(self.client.get(f"/api/v1/recetas/{receta_id}").status_code, 404)

    def test_medico_solo_sus_emitidas_y_admin_tenant(self):
        self._emitir()  # médico 3
        self._emitir(_payload_consulta(id_consulta=46), key="m7", user_id=7)  # médico 7
        self._auth_as(2)
        self.assertEqual(self.client.get("/api/v1/recetas").json()["total"], 1)
        self._auth_as(1)
        self.assertEqual(self.client.get("/api/v1/recetas").json()["total"], 2)

    def test_aislamiento_multitenant(self):
        receta_id = self._emitir().json()["id_receta"]
        self._auth_as(6)  # médico clínica 2
        self.assertEqual(self.client.get("/api/v1/recetas").json()["total"], 0)
        self.assertEqual(self.client.get(f"/api/v1/recetas/{receta_id}").status_code, 404)
        self.assertEqual(
            self.client.post(f"/api/v1/recetas/{receta_id}/anular",
                             json={"motivo_anulacion": "Motivo válido con más de quince caracteres"}).status_code,
            404)

    def test_sin_delete_ni_put(self):
        receta_id = self._emitir().json()["id_receta"]
        self.assertEqual(self.client.delete(f"/api/v1/recetas/{receta_id}").status_code, 405)
        self.assertEqual(self.client.put(f"/api/v1/recetas/{receta_id}",
                                         json={}).status_code, 405)

    # ---------------- idempotencia y concurrencia ---------------- #

    def test_idempotencia_misma_clave_mismo_payload(self):
        r1 = self._emitir(key="idem-1")
        r2 = self._emitir(key="idem-1")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["id_receta"], r2.json()["id_receta"])
        self.assertEqual(self._count("recetas"), 1)
        self.assertEqual(self._count("documentos_clinicos"), 1)

    def test_idempotencia_misma_clave_otro_payload_409(self):
        self._emitir(key="idem-2")
        resp = self._emitir(_payload_consulta(manual=True), key="idem-2")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "PRESCRIPTION_CONFLICT")

    def test_concurrencia_folios_unicos(self):
        import os
        db_path = os.path.join(self._tmpdir.name, "concurrent.db")
        file_engine = create_engine(f"sqlite:///{db_path}")
        FileSession = sessionmaker(bind=file_engine, autocommit=False, autoflush=False,
                                   expire_on_commit=False)
        Base.metadata.create_all(file_engine)
        seed = FileSession()
        try:
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'C1', 'ACTIVO')"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES (2, 1, 'MEDICO', 'ACTIVO')"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo,"
                " password_hash, estado, token_version, notificaciones_push, notificaciones_email,"
                " notificaciones_sms) VALUES (2, 1, 2, 'M', 'Uno', 'm@t.com', 'h', 'activo', 0, 1, 1, 0)"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO permisos (id_permiso, nombre, descripcion, modulo, accion, estado) VALUES "
                "(1, 'prescriptions:issue', 'x', 'prescriptions', 'issue', 'ACTIVO')"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (2, 1)"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO pacientes (id_paciente, id_clinica, nombres, apellidos, ci,"
                " fecha_nacimiento, genero, telefono, estado) VALUES "
                "(10, 1, 'P', 'Uno', '111', '1990-01-01', 'F', '1', 'ACTIVO')"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO medicos (id_medico, id_usuario, matricula_profesional, estado) VALUES "
                "(3, 2, 'MP-1', 'activo')"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO citas (id_cita, id_paciente, id_medico, estado) VALUES (100, 10, 3, 'X')"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO historias_clinicas (id_historia, id_clinica, id_paciente, numero_historia)"
                " VALUES (1, 1, 10, 'HCE-1')"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO consultas (id_consulta, id_clinica, id_historia, id_cita, id_medico,"
                " motivo_consulta, sintomas, evolucion, plan_medico)"
                " VALUES (45, 1, 1, 100, 3, 'm', 's', 'e', 'p')"))
            seed.execute(__import__("sqlalchemy").text(
                "INSERT INTO medicamentos (id_medicamento, nombre, principio_activo, concentracion,"
                " forma_farmaceutica, estado) VALUES "
                "(14, 'Amoxicilina', 'Amoxicilina', '500 mg', 'Comprimido', 'ACTIVO')"))
            seed.commit()
            user = seed.query(Usuario).filter(Usuario.id_usuario == 2).first()
            seed.expunge(user)
        finally:
            seed.close()

        from app.modules.medical_records.prescriptions.schemas import RecetaCreateRequest
        folios, errores = [], []
        lock = threading.Lock()

        def worker(i: int):
            db = FileSession()
            try:
                payload = RecetaCreateRequest.model_validate(_payload_consulta())
                receta, _ = rx_service.emitir_receta(
                    db, user=user, tenant_id=1, payload=payload,
                    payload_raw=payload.model_dump(mode="json"),
                    idempotency_key=f"conc-{i}", client_ip=None)
                with lock:
                    folios.append(receta.folio)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errores.append(repr(exc))
            finally:
                db.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        file_engine.dispose()
        self.assertEqual(errores, [])
        self.assertEqual(len(set(folios)), 8)
        numeros = sorted(int(f.rsplit("-", 1)[1]) for f in folios)
        self.assertEqual(numeros, list(range(1, 9)))

    # ---------------- rollback ---------------- #

    def test_rollback_ante_fallo_y_sin_huerfanos(self):
        archivos_antes = self._storage_files()
        with mock.patch.object(rx_service, "build_receta_pdf",
                               side_effect=RuntimeError("boom PDF")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/v1/recetas", json=_payload_consulta(),
                                 headers={"Idempotency-Key": "rb-1"})
        self.assertEqual(self._count("recetas"), 0)
        self.assertEqual(self._count("receta_detalle"), 0)
        self.assertEqual(self._count("documentos_clinicos"), 0)
        self.assertEqual(self._count("receta_idempotencia"), 0)
        self.assertEqual(
            self._count("auditoria"), 0)
        self.assertEqual(self._storage_files(), archivos_antes)

    # ---------------- anulación ---------------- #

    def test_anulacion_medico_emisor(self):
        body = self._emitir().json()
        pdf_antes = self.client.get(f"/api/v1/recetas/{body['id_receta']}/pdf").content
        resp = self.client.post(f"/api/v1/recetas/{body['id_receta']}/anular", json={
            "motivo_anulacion": "Ajuste del esquema por resultado posterior de antibiograma."})
        self.assertEqual(resp.status_code, 200, resp.text)
        anulada = resp.json()
        self.assertEqual(anulada["estado"], "ANULADA")
        self.assertIsNotNone(anulada["fecha_anulacion"])
        pdf_despues = self.client.get(f"/api/v1/recetas/{body['id_receta']}/pdf").content
        self.assertEqual(hashlib.sha256(pdf_antes).hexdigest(),
                         hashlib.sha256(pdf_despues).hexdigest())
        db = self._db()
        try:
            estado_doc = db.execute(__import__("sqlalchemy").text(
                "SELECT estado FROM documentos_clinicos")).first()[0]
            self.assertEqual(estado_doc, "ANULADO")
            audit = db.execute(__import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM auditoria WHERE accion='ANULAR_RECETA'")).scalar()
            self.assertEqual(audit, 1)
        finally:
            db.close()

    def test_doble_anulacion_409(self):
        receta_id = self._emitir().json()["id_receta"]
        motivo = {"motivo_anulacion": "Ajuste del esquema por resultado posterior."}
        self.assertEqual(self.client.post(f"/api/v1/recetas/{receta_id}/anular",
                                          json=motivo).status_code, 200)
        resp = self.client.post(f"/api/v1/recetas/{receta_id}/anular", json=motivo)
        self.assertEqual(resp.status_code, 409)

    def test_anular_vencida_409(self):
        receta_id = self._emitir(_payload_consulta(dias_vigencia=1), key="venc-1").json()["id_receta"]
        db = self._db()
        try:
            db.execute(__import__("sqlalchemy").text(
                "UPDATE recetas SET fecha_vencimiento=:ayer WHERE id_receta=:rid"),
                {"ayer": (date.today() - timedelta(days=1)).isoformat(), "rid": receta_id})
            db.commit()
        finally:
            db.close()
        resp = self.client.post(f"/api/v1/recetas/{receta_id}/anular", json={
            "motivo_anulacion": "Motivo válido con más de quince caracteres"})
        self.assertEqual(resp.status_code, 409)

    def test_admin_sin_permiso_cancel_403_y_con_permiso_200(self):
        receta_id = self._emitir().json()["id_receta"]
        motivo = {"motivo_anulacion": "Ajuste del esquema por resultado posterior."}
        db = self._db()
        try:
            db.execute(__import__("sqlalchemy").text(
                "DELETE FROM rol_permisos WHERE id_rol=1 AND id_permiso=4"))
            db.commit()
        finally:
            db.close()
        self._auth_as(1)
        self.assertEqual(self.client.post(f"/api/v1/recetas/{receta_id}/anular",
                                          json=motivo).status_code, 403)
        db = self._db()
        try:
            db.execute(__import__("sqlalchemy").text(
                "INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (1, 4)"))
            db.commit()
        finally:
            db.close()
        self.assertEqual(self.client.post(f"/api/v1/recetas/{receta_id}/anular",
                                          json=motivo).status_code, 200)

    def test_motivo_corto_422(self):
        receta_id = self._emitir().json()["id_receta"]
        resp = self.client.post(f"/api/v1/recetas/{receta_id}/anular",
                                json={"motivo_anulacion": "Corto"})
        self.assertEqual(resp.status_code, 422)

    # ---------------- sustitución ---------------- #

    def test_sustitucion_valida_e_invalida(self):
        id_a = self._emitir(key="sust-a").json()["id_receta"]
        id_b = self._emitir(key="sust-b").json()["id_receta"]
        motivo = {"motivo_anulacion": "Se emite receta corregida con ajuste de dosis.",
                  "id_receta_sustituta": id_b}
        resp = self.client.post(f"/api/v1/recetas/{id_a}/anular", json=motivo)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["id_receta_sustituta"], id_b)
        # Autorreferencia
        resp = self.client.post(f"/api/v1/recetas/{id_b}/anular", json={
            "motivo_anulacion": "Se emite receta corregida con ajuste de dosis.",
            "id_receta_sustituta": id_b})
        self.assertEqual(resp.status_code, 409)
        # Ciclo: B sustituye a A que ya apunta a B
        resp = self.client.post(f"/api/v1/recetas/{id_b}/anular", json={
            "motivo_anulacion": "Se emite receta corregida con ajuste de dosis.",
            "id_receta_sustituta": id_a})
        self.assertEqual(resp.status_code, 409)

    # ---------------- validación pública ---------------- #

    def _emitir_con_token_fijo(self, dias_vigencia=30, key="pub-1", id_consulta=45):
        with mock.patch.object(rx_service, "generate_verification_token",
                               return_value=(FIXED_TOKEN, FIXED_HASH)):
            resp = self._emitir(_payload_consulta(id_consulta=id_consulta,
                                                  dias_vigencia=dias_vigencia), key=key)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def test_validacion_vigente(self):
        body = self._emitir_con_token_fijo()
        resp = self.client.get(f"/api/v1/recetas/validar/{FIXED_TOKEN}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        data = resp.json()
        self.assertTrue(data["valida"])
        self.assertEqual(data["estado"], "EMITIDA")
        self.assertEqual(data["folio"], body["folio"])
        self.assertEqual(data["paciente"]["nombre"], "María R. M.")
        self.assertEqual(data["paciente"]["documento_identidad"], "****910")
        self.assertEqual(data["institucion"], "Hospital San Juan de Dios - Santa Cruz")
        self.assertEqual(data["medico_emisor"]["matricula"], "MP-84920-SC")
        self.assertEqual(len(data["medicamentos_prescritos"]), 1)
        for clave in ("diagnostico", "alergia", "telefono", "correo", "direccion",
                      "observaciones", "historia"):
            self.assertNotIn(clave, json.dumps(data).lower())

    def test_validacion_vencida_y_anulada(self):
        self._emitir_con_token_fijo(dias_vigencia=1, key="pub-v")
        # Simular paso del tiempo sin manipular el payload firmado: la
        # integridad exige que fecha_vencimiento firmada no cambie en BD.
        # Se parcha _today() durante la validación para que la receta
        # aparezca vencida sin alterar la firma.
        with mock.patch.object(rx_service, "_today",
                               return_value=date.today() + timedelta(days=2)):
            data = self.client.get(f"/api/v1/recetas/validar/{FIXED_TOKEN}").json()
        self.assertFalse(data["valida"])
        self.assertEqual(data["estado"], "VENCIDA")

        self._reset_data()
        with mock.patch.object(rx_service, "generate_verification_token",
                               return_value=(FIXED_TOKEN, FIXED_HASH)):
            receta_id = self._emitir(key="pub-a").json()["id_receta"]
        self.client.post(f"/api/v1/recetas/{receta_id}/anular", json={
            "motivo_anulacion": "Ajuste del esquema por resultado posterior."})
        data = self.client.get(f"/api/v1/recetas/validar/{FIXED_TOKEN}").json()
        self.assertFalse(data["valida"])
        self.assertEqual(data["estado"], "ANULADA")

    def test_validacion_inexistente_uniforme(self):
        resp = self.client.get("/api/v1/recetas/validar/" + "Z" * 43)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"valida": False, "estado": "NO_ENCONTRADA"})
        resp = self.client.get("/api/v1/recetas/validar/codigo-malformado!!!")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"valida": False, "estado": "NO_ENCONTRADA"})

    def test_rate_limit_por_ip(self):
        # Códigos distintos para no activar el límite por código (10/min)
        for i in range(30):
            codigo = f"9{i:042d}"
            resp = self.client.get(f"/api/v1/recetas/validar/{codigo}")
            self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/api/v1/recetas/validar/" + "8" * 43)
        self.assertEqual(resp.status_code, 429)
        self.assertIn("Retry-After", resp.headers)

    def test_rate_limit_por_codigo(self):
        for i in range(10):
            resp = self.client.get("/api/v1/recetas/validar/" + "Z" * 43,
                                   headers={"X-Forwarded-For": f"10.0.0.{i}"})
            self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/api/v1/recetas/validar/" + "Z" * 43,
                               headers={"X-Forwarded-For": "10.0.0.99"})
        self.assertEqual(resp.status_code, 429)
        self.assertIn("Retry-After", resp.headers)

    def test_telemetria_anonimizada(self):
        self._emitir_con_token_fijo()
        # Sin proxies de confianza (TRUSTED_PROXY_IPS vacío por defecto),
        # X-Forwarded-For se ignora y se usa request.client.host
        # ("testclient" en TestClient). La IP nunca se persiste en claro.
        self.client.get("/api/v1/recetas/validar/" + FIXED_TOKEN,
                        headers={"X-Forwarded-For": "203.0.113.7"})
        self.client.get("/api/v1/recetas/validar/" + "Z" * 43,
                        headers={"X-Forwarded-For": "203.0.113.7"})
        db = self._db()
        try:
            rows = db.execute(__import__("sqlalchemy").text(
                "SELECT codigo_hash, ip_hash, resultado FROM receta_validacion_intentos")).all()
            self.assertEqual(len(rows), 2)
            esperado_ip = hmac.new(b"test-hmac-secret", b"testclient",
                                   hashlib.sha256).hexdigest()
            for codigo_hash, ip_hash, resultado in rows:
                self.assertEqual(ip_hash, esperado_ip)
                self.assertEqual(len(codigo_hash), 64)
                self.assertNotIn("203.0.113.7", codigo_hash + ip_hash + resultado)
            # La validación anónima no fabrica eventos de auditoría clínica
            audit = db.execute(__import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM auditoria WHERE accion LIKE 'VALIDAR%'")).scalar()
            self.assertEqual(audit, 0)
        finally:
            db.close()

    # ---------------- utilidades puras ---------------- #

    def test_enmascaramiento(self):
        self.assertEqual(mask_patient_name("María Reneé Morales"), "María R. M.")
        self.assertEqual(mask_patient_name("Juan"), "Juan")
        self.assertEqual(mask_document("1234910"), "****910")
        self.assertEqual(mask_document("ABC"), "***")
        self.assertEqual(mask_document(""), "")

    def test_canonicalizacion_rfc8785(self):
        self.assertEqual(canonicalize_jcs({"b": 1, "a": [3, 2]}), b'{"a":[3,2],"b":1}')
        self.assertEqual(canonicalize_jcs({"z": None, "m": True}), b'{"m":true,"z":null}')


if __name__ == "__main__":
    unittest.main()
