"""Pruebas de Órdenes de Laboratorio (CU10).

Cubren: creación en borrador, firma digital + PDF + indexación HCE,
listado con alcance por rol, catálogo de exámenes, descarga.
"""
import unittest
from datetime import date, datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.modules.auth.models import Usuario
from app.modules.medical_records.laboratory_orders.models import ExamenLaboratorio, OrdenLaboratorio


class CU10LaboratoryOrdersTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        cls._create_schema()

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)

    @classmethod
    def _create_schema(cls):
        with cls.engine.begin() as conn:
            conn.exec_driver_sql("""
                CREATE TABLE clinicas (
                    id_clinica INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO'
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE roles (
                    id_rol INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER,
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO',
                    fecha_creacion TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE usuarios (
                    id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NOT NULL,
                    id_rol INTEGER NOT NULL,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL,
                    correo TEXT NOT NULL UNIQUE,
                    telefono TEXT,
                    password_hash TEXT NOT NULL,
                    foto_perfil TEXT,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO',
                    notificaciones_push INTEGER NOT NULL DEFAULT 1,
                    notificaciones_email INTEGER NOT NULL DEFAULT 1,
                    notificaciones_sms INTEGER NOT NULL DEFAULT 0,
                    token_version INTEGER NOT NULL DEFAULT 0,
                    fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    fecha_actualizacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE pacientes (
                    id_paciente INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_usuario INTEGER,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE examenes_laboratorio (
                    id_examen INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NOT NULL,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    precio_referencia INTEGER,
                    activo TEXT NOT NULL DEFAULT 'SI',
                    requiere_ayuno INTEGER NOT NULL DEFAULT 0,
                    tiempo_entrega_horas INTEGER NOT NULL DEFAULT 24,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE UNIQUE INDEX idx_examenes_clinica_codigo
                ON examenes_laboratorio (id_clinica, codigo)
            """)
            conn.exec_driver_sql("""
                CREATE TABLE ordenes_laboratorio (
                    id_orden INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NOT NULL,
                    id_paciente INTEGER NOT NULL,
                    id_cita INTEGER,
                    id_medico INTEGER NOT NULL,
                    examenes TEXT NOT NULL,
                    firma_digital TEXT,
                    fecha_orden DATE,
                    estado TEXT NOT NULL DEFAULT 'BORRADOR',
                    archivo_url TEXT,
                    hash_archivo TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE documentos_clinicos (
                    id_documento INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NOT NULL,
                    id_paciente INTEGER,
                    id_cita INTEGER,
                    tipo_documento TEXT NOT NULL,
                    titulo TEXT NOT NULL,
                    descripcion TEXT,
                    archivo_url TEXT NOT NULL,
                    hash_archivo TEXT NOT NULL,
                    firmado_por INTEGER,
                    fecha_documento DATE NOT NULL,
                    metadatos TEXT,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE permisos (
                    id_permiso INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL UNIQUE,
                    descripcion TEXT,
                    modulo TEXT NOT NULL,
                    accion TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO'
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE rol_permisos (
                    id_rol INTEGER NOT NULL,
                    id_permiso INTEGER NOT NULL,
                    PRIMARY KEY (id_rol, id_permiso)
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE auditoria (
                    id_auditoria INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NOT NULL,
                    id_usuario INTEGER NOT NULL,
                    tabla_afectada TEXT NOT NULL,
                    registro_id INTEGER NOT NULL,
                    accion TEXT NOT NULL,
                    descripcion TEXT,
                    direccion_ip TEXT
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE sesiones_activas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    jti VARCHAR(64) NOT NULL UNIQUE,
                    id_usuario BIGINT NOT NULL,
                    id_clinica BIGINT,
                    creada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ultima_actividad TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    revocada_en TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE token_blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token VARCHAR(500) NOT NULL,
                    revoked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Datos base
            conn.exec_driver_sql("INSERT INTO clinicas (id_clinica, nombre) VALUES (1, 'Clínica Test')")
            conn.exec_driver_sql("INSERT INTO roles (id_rol, nombre) VALUES (1, 'ADMIN'), (2, 'MEDICO'), (3, 'RECEPCION'), (4, 'PACIENTE')")
            conn.exec_driver_sql("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, token_version)
                VALUES
                (1, 1, 2, 'Dr. Juan', 'Pérez', 'medico@test.com', 'x', 'ACTIVO', 0),
                (2, 1, 2, 'Dra. Ana', 'Gómez', 'medico2@test.com', 'x', 'ACTIVO', 0),
                (3, 1, 3, 'Recepcionista', 'Uno', 'recepcion@test.com', 'x', 'ACTIVO', 0),
                (4, 1, 4, 'Paciente', 'Uno', 'paciente@test.com', 'x', 'ACTIVO', 0)
            """)
            conn.exec_driver_sql("""
                INSERT INTO pacientes (id_paciente, id_usuario, nombres, apellidos)
                VALUES (10, 4, 'Carlos', 'Mamani'), (11, NULL, 'Luis', 'García')
            """)
            conn.exec_driver_sql("""
                INSERT INTO examenes_laboratorio (id_clinica, codigo, nombre, categoria, activo)
                VALUES
                (1, 'HEMOGRAMA', 'Hemograma Completo', 'HEMATOLOGIA', 'SI'),
                (1, 'GLUCOSA', 'Glucosa en Sangre', 'BIOQUIMICA', 'SI'),
                (1, 'CREATININA', 'Creatinina Sérica', 'BIOQUIMICA', 'SI'),
                (1, 'UREA', 'Urea Sérica', 'BIOQUIMICA', 'SI')
            """)
            # Permisos CU10
            conn.exec_driver_sql("""
                INSERT INTO permisos (nombre, descripcion, modulo, accion) VALUES
                ('lab_orders:create', 'Crear y firmar órdenes de laboratorio', 'laboratory_orders', 'create'),
                ('lab_orders:read', 'Leer órdenes de laboratorio', 'laboratory_orders', 'read'),
                ('lab_orders:download', 'Descargar PDF de órdenes', 'laboratory_orders', 'download')
            """)
            conn.exec_driver_sql("""
                INSERT INTO rol_permisos (id_rol, id_permiso)
                SELECT r.id_rol, p.id_permiso FROM roles r, permisos p
                WHERE r.nombre IN ('ADMIN', 'MEDICO') AND p.nombre IN ('lab_orders:create', 'lab_orders:read', 'lab_orders:download')
            """)
            conn.exec_driver_sql("""
                INSERT INTO rol_permisos (id_rol, id_permiso)
                SELECT r.id_rol, p.id_permiso FROM roles r, permisos p
                WHERE r.nombre = 'RECEPCION' AND p.nombre IN ('lab_orders:read', 'lab_orders:download')
            """)
            conn.exec_driver_sql("""
                INSERT INTO rol_permisos (id_rol, id_permiso)
                SELECT r.id_rol, p.id_permiso FROM roles r, permisos p
                WHERE r.nombre = 'PACIENTE' AND p.nombre = 'lab_orders:download'
            """)

    def setUp(self):
        self.client = TestClient(app)
        db = self.SessionLocal()
        try:
            db.query(OrdenLaboratorio).delete()
            db.commit()
        finally:
            db.close()

    def _token_medico(self, user_id=1, medico_id=1):
        return create_access_token({
            "sub": str(user_id),
            "jti": f"jti-medico-{medico_id}-{datetime.now(timezone.utc).timestamp()}",
            "token_version": 0
        })

    def _token_recepcion(self):
        return create_access_token({
            "sub": "3",
            "jti": f"jti-recep-{datetime.now(timezone.utc).timestamp()}",
            "token_version": 0
        })

    def _token_admin(self):
        return create_access_token({
            "sub": "1",
            "jti": f"jti-admin-{datetime.now(timezone.utc).timestamp()}",
            "token_version": 0
        })

    # ------------------------------------------------------------------ #
    # Catálogo de exámenes
    # ------------------------------------------------------------------ #
    def test_catalogo_examenes_devuelve_solo_activos(self):
        token = self._token_medico()
        response = self.client.get(
            "/api/v1/ordenes-laboratorio/examenes",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data), 4)
        for e in data:
            self.assertEqual(e["activo"], "SI")

    # ------------------------------------------------------------------ #
    # Creación en borrador
    # ------------------------------------------------------------------ #
    def test_medico_crea_orden_borrador_exitoso(self):
        token = self._token_medico()
        response = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "id_paciente": 10,
                "examenes": [
                    {"codigo": "HEMOGRAMA", "indicaciones": "En ayunas"},
                    {"codigo": "GLUCOSA", "indicaciones": "Post-prandial"}
                ]
            }
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["estado"], "BORRADOR")
        self.assertEqual(data["id_medico"], 1)
        self.assertEqual(len(data["examenes"]), 2)

    def test_creacion_rechaza_examen_inexistente(self):
        token = self._token_medico()
        response = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "id_paciente": 10,
                "examenes": [{"codigo": "EXAMEN_FALSO"}]
            }
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Examen no encontrado", response.json()["detail"])

    def test_creacion_rechaza_sin_examenes(self):
        token = self._token_medico()
        response = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token}"},
            json={"id_paciente": 10, "examenes": []}
        )
        self.assertEqual(response.status_code, 422)

    def test_creacion_rechaza_paciente_inexistente(self):
        token = self._token_medico()
        response = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token}"},
            json={"id_paciente": 999, "examenes": [{"codigo": "HEMOGRAMA"}]}
        )
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------ #
    # Firma y emisión
    # ------------------------------------------------------------------ #
    def test_medico_firma_su_orden_y_se_indexa_en_hce(self):
        token = self._token_medico()
        # Crear borrador
        create_resp = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token}"},
            json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]}
        )
        self.assertEqual(create_resp.status_code, 201)
        id_orden = create_resp.json()["id_orden"]

        # Firmar
        firmar_resp = self.client.post(
            f"/api/v1/ordenes-laboratorio/{id_orden}/firmar",
            headers={"Authorization": f"Bearer {token}"},
            json={}
        )
        self.assertEqual(firmar_resp.status_code, 200)
        data = firmar_resp.json()
        self.assertEqual(data["estado"], "FIRMADA")
        self.assertIsNotNone(data["firma_digital"])
        self.assertEqual(len(data["firma_digital"]), 64)
        self.assertIsNotNone(data["archivo_url"])
        self.assertIsNotNone(data["hash_archivo"])
        self.assertEqual(len(data["hash_archivo"]), 64)

        # Verificar indexación en HCE (documentos_clinicos)
        db = self.SessionLocal()
        try:
            from app.modules.medical_records.clinical_documents.models import DocumentoClinico
            # SQLite usa json_extract para consultar JSON; el valor en BD es numérico (no string)
            doc = db.query(DocumentoClinico).filter(
                DocumentoClinico.tipo_documento == "ORDEN_LAB",
                sql_text("json_extract(metadatos, '$.id_orden_laboratorio') = :id_orden"),
            ).params(id_orden=id_orden).first()
            self.assertIsNotNone(doc)
            self.assertEqual(doc.tipo_documento, "ORDEN_LAB")
            self.assertEqual(doc.estado, "ACTIVO")
            self.assertEqual(doc.firmado_por, 1)
        finally:
            db.close()

    def test_medico_no_puede_firmar_orden_ajena(self):
        # Médico 1 crea orden
        token1 = self._token_medico(1, 1)
        create_resp = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token1}"},
            json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]}
        )
        id_orden = create_resp.json()["id_orden"]

        # Médico 2 intenta firmar
        token2 = self._token_medico(2, 2)
        firmar_resp = self.client.post(
            f"/api/v1/ordenes-laboratorio/{id_orden}/firmar",
            headers={"Authorization": f"Bearer {token2}"},
            json={}
        )
        self.assertEqual(firmar_resp.status_code, 403)
        self.assertIn("médico creador", firmar_resp.json()["detail"])

    def test_firmar_orden_ya_firmada_retorna_409(self):
        token = self._token_medico()
        create_resp = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token}"},
            json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]}
        )
        id_orden = create_resp.json()["id_orden"]

        # Primera firma
        self.client.post(
            f"/api/v1/ordenes-laboratorio/{id_orden}/firmar",
            headers={"Authorization": f"Bearer {token}"},
            json={}
        )
        # Segunda firma
        firmar_resp = self.client.post(
            f"/api/v1/ordenes-laboratorio/{id_orden}/firmar",
            headers={"Authorization": f"Bearer {token}"},
            json={}
        )
        self.assertEqual(firmar_resp.status_code, 409)

    # ------------------------------------------------------------------ #
    # Listado con alcance por rol
    # ------------------------------------------------------------------ #
    def test_medico_solo_ve_sus_propias_ordenes(self):
        token1 = self._token_medico(1, 1)
        token2 = self._token_medico(2, 2)

        # Médico 1 crea 2 órdenes
        for _ in range(2):
            self.client.post(
                "/api/v1/ordenes-laboratorio",
                headers={"Authorization": f"Bearer {token1}"},
                json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]}
            )
        # Médico 2 crea 1 orden
        self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token2}"},
            json={"id_paciente": 11, "examenes": [{"codigo": "GLUCOSA"}]}
        )

        # Médico 1 lista
        resp1 = self.client.get(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token1}"}
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["total"], 2)

        # Médico 2 lista
        resp2 = self.client.get(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token2}"}
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["total"], 1)

    def test_recepcion_ve_todas_las_ordenes(self):
        token1 = self._token_medico(1, 1)
        token2 = self._token_medico(2, 2)
        token_recep = self._token_recepcion()

        # Cada médico crea 1
        self.client.post("/api/v1/ordenes-laboratorio", headers={"Authorization": f"Bearer {token1}"},
                         json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]})
        self.client.post("/api/v1/ordenes-laboratorio", headers={"Authorization": f"Bearer {token2}"},
                         json={"id_paciente": 11, "examenes": [{"codigo": "GLUCOSA"}]})
        self.client.post("/api/v1/ordenes-laboratorio", headers={"Authorization": f"Bearer {token1}"},
                         json={"id_paciente": 10, "examenes": [{"codigo": "CREATININA"}]})

        # Recepción lista
        resp = self.client.get(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token_recep}"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 3)

    def test_filtrado_por_estado_y_paciente(self):
        token = self._token_medico()
        # Crear 1 borrador, 1 firmada
        borrador = self.client.post(
            "/api/v1/ordenes-laboratorio", headers={"Authorization": f"Bearer {token}"},
            json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]}
        ).json()["id_orden"]
        firmada = self.client.post(
            "/api/v1/ordenes-laboratorio", headers={"Authorization": f"Bearer {token}"},
            json={"id_paciente": 10, "examenes": [{"codigo": "GLUCOSA"}]}
        ).json()["id_orden"]
        self.client.post(
            f"/api/v1/ordenes-laboratorio/{firmada}/firmar",
            headers={"Authorization": f"Bearer {token}"}, json={}
        )

        # Filtrar solo firmadas
        resp = self.client.get(
            "/api/v1/ordenes-laboratorio?estado=FIRMADA",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)
        self.assertEqual(resp.json()["items"][0]["estado"], "FIRMADA")

    # ------------------------------------------------------------------ #
    # Detalle y acceso
    # ------------------------------------------------------------------ #
    def test_medico_no_puede_ver_detalle_orden_ajena(self):
        token1 = self._token_medico(1, 1)
        token2 = self._token_medico(2, 2)

        create_resp = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token1}"},
            json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]}
        )
        id_orden = create_resp.json()["id_orden"]

        # Médico 2 intenta ver
        resp = self.client.get(
            f"/api/v1/ordenes-laboratorio/{id_orden}",
            headers={"Authorization": f"Bearer {token2}"}
        )
        self.assertEqual(resp.status_code, 404)  # 404 para no filtrar existencia

    # ------------------------------------------------------------------ #
    # Descarga (reusa CU12)
    # ------------------------------------------------------------------ #
    def test_descarga_orden_firmada_genera_url_firmada(self):
        token = self._token_medico()
        create_resp = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token}"},
            json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]}
        )
        id_orden = create_resp.json()["id_orden"]
        self.client.post(
            f"/api/v1/ordenes-laboratorio/{id_orden}/firmar",
            headers={"Authorization": f"Bearer {token}"}, json={}
        )

        dl_resp = self.client.get(
            f"/api/v1/ordenes-laboratorio/{id_orden}/download",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(dl_resp.status_code, 200)
        data = dl_resp.json()
        self.assertIn("url_firmada", data)
        self.assertLessEqual(data["expira_en"], 900)
        self.assertEqual(data["content_type"], "application/pdf")

    def test_descarga_orden_no_firmada_retorna_404(self):
        token = self._token_medico()
        create_resp = self.client.post(
            "/api/v1/ordenes-laboratorio",
            headers={"Authorization": f"Bearer {token}"},
            json={"id_paciente": 10, "examenes": [{"codigo": "HEMOGRAMA"}]}
        )
        id_orden = create_resp.json()["id_orden"]

        dl_resp = self.client.get(
            f"/api/v1/ordenes-laboratorio/{id_orden}/download",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(dl_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()