"""Pruebas automatizadas del módulo clinical-documents (CU12).

Cubren los criterios de aceptación de openspec/contracts/clinical-documents.md:
aislamiento estricto multitenant, acceso del paciente a sus propios documentos,
restricción de resultados de laboratorio para RECEPCION, y descarga segura
con auditoría y notificación. (tarea 5.1 - cobertura >=80%)
"""
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.clinical_documents import storage as storage_module
from app.modules.medical_records.clinical_documents.storage import storage

HASH_OK = "a" * 64  # SHA-256 hex válido (64 caracteres)


class CU12ClinicalDocumentsTestCase(unittest.TestCase):
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
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    @classmethod
    def _create_schema(cls):
        with cls.engine.begin() as conn:
            conn.exec_driver_sql("""
                CREATE TABLE clinicas (
                    id_clinica INTEGER PRIMARY KEY,
                    nombre TEXT NOT NULL
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE roles (
                    id_rol INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NULL,
                    nombre TEXT NOT NULL,
                    descripcion TEXT NULL,
                    estado TEXT NOT NULL,
                    fecha_creacion TIMESTAMP NULL
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE permisos (
                    id_permiso INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    descripcion TEXT NULL,
                    modulo TEXT NOT NULL,
                    accion TEXT NOT NULL,
                    estado TEXT NOT NULL
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
                CREATE TABLE usuarios (
                    id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NULL,
                    id_rol INTEGER NULL,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL,
                    correo TEXT NOT NULL UNIQUE,
                    telefono TEXT NULL,
                    password_hash TEXT NOT NULL,
                    token_version INTEGER NOT NULL DEFAULT 0,
                    foto_perfil TEXT NULL,
                    estado TEXT NOT NULL,
                    notificaciones_push INTEGER NOT NULL DEFAULT 1,
                    notificaciones_email INTEGER NOT NULL DEFAULT 1,
                    notificaciones_sms INTEGER NOT NULL DEFAULT 0,
                    fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    fecha_actualizacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE pacientes (
                    id_paciente INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NULL,
                    id_usuario INTEGER NULL UNIQUE,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL,
                    ci TEXT NOT NULL,
                    complemento TEXT NULL,
                    fecha_nacimiento DATE NOT NULL,
                    genero TEXT NOT NULL,
                    telefono TEXT NOT NULL,
                    correo TEXT NULL,
                    direccion TEXT NULL,
                    ciudad TEXT NULL,
                    tipo_sangre TEXT NULL,
                    alergias TEXT NULL,
                    antecedentes_patologicos TEXT NULL,
                    contacto_emergencia_nombre TEXT NULL,
                    contacto_emergencia_telefono TEXT NULL,
                    contacto_emergencia_parentesco TEXT NULL,
                    seguro_medico TEXT NULL,
                    numero_seguro TEXT NULL,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE documentos_clinicos (
                    id_documento INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NOT NULL,
                    id_paciente INTEGER NULL,
                    id_cita INTEGER NULL,
                    tipo_documento TEXT NOT NULL,
                    titulo TEXT NOT NULL,
                    descripcion TEXT NULL,
                    archivo_url TEXT NOT NULL,
                    hash_archivo TEXT NOT NULL,
                    firmado_por INTEGER NULL,
                    fecha_documento DATE NOT NULL,
                    metadatos TEXT NULL,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE auditoria (
                    id_auditoria INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NOT NULL,
                    id_usuario INTEGER NOT NULL,
                    tabla_afectada TEXT NULL,
                    registro_id INTEGER NULL,
                    accion TEXT NOT NULL,
                    descripcion TEXT NULL,
                    datos_anteriores TEXT NULL,
                    datos_nuevos TEXT NULL,
                    direccion_ip TEXT NULL,
                    fecha_hora TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("""
                CREATE TABLE notificaciones (
                    id_notificacion INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_usuario INTEGER NOT NULL,
                    tipo TEXT NULL,
                    canal TEXT NULL,
                    titulo TEXT NULL,
                    mensaje TEXT NULL,
                    fecha_programada TIMESTAMP NULL,
                    fecha_envio TIMESTAMP NULL,
                    fecha_lectura TIMESTAMP NULL,
                    estado TEXT NOT NULL DEFAULT 'PENDIENTE'
                )
            """)

    def setUp(self):
        self._reset_data()

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _reset_data(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM notificaciones")
            conn.exec_driver_sql("DELETE FROM auditoria")
            conn.exec_driver_sql("DELETE FROM documentos_clinicos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM rol_permisos")
            conn.exec_driver_sql("DELETE FROM permisos")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre) VALUES "
                "(1, 'Clinica Central'), (2, 'Clinica Norte')"
            )
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, id_clinica, nombre, descripcion, estado) VALUES "
                "(1, NULL, 'ADMIN', 'Admin', 'ACTIVO'),"
                "(2, NULL, 'MEDICO', 'Medico', 'ACTIVO'),"
                "(3, NULL, 'RECEPCION', 'Recepcion', 'ACTIVO'),"
                "(4, NULL, 'PACIENTE', 'Paciente', 'ACTIVO')"
            )
            self._seed_permisos(conn)
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, "
                "telefono, password_hash, foto_perfil, estado) VALUES "
                "(1, 1, 1, 'Admin', 'Sistema', 'admin@t.com', '70000000', 'h', NULL, 'activo'),"
                "(2, 1, 2, 'Doc', 'Uno', 'medico@t.com', '70000001', 'h', NULL, 'activo'),"
                "(3, 1, 3, 'Recep', 'Uno', 'recep@t.com', '70000002', 'h', NULL, 'activo'),"
                "(4, 1, 4, 'Carlos', 'Mamani', 'carlos@t.com', '70000003', 'h', NULL, 'activo'),"
                "(5, 1, 4, 'Ana', 'Perez', 'ana@t.com', '70000004', 'h', NULL, 'activo'),"
                "(6, 2, 2, 'Doc', 'Norte', 'norte@t.com', '70000005', 'h', NULL, 'activo')"
            )
            conn.exec_driver_sql(
                "INSERT INTO pacientes (id_paciente, id_clinica, id_usuario, nombres, apellidos, ci, "
                "fecha_nacimiento, genero, telefono, estado) VALUES "
                "(1, 1, 4, 'Carlos', 'Mamani', '1111111', '1990-01-01', 'M', '70000003', 'ACTIVO'),"
                "(2, 1, 5, 'Ana', 'Perez', '2222222', '1992-02-02', 'F', '70000004', 'ACTIVO'),"
                "(3, 2, NULL, 'Luis', 'Gomez', '3333333', '1988-03-03', 'M', '70000005', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO documentos_clinicos (id_documento, id_clinica, id_paciente, id_cita, "
                "tipo_documento, titulo, descripcion, archivo_url, hash_archivo, firmado_por, "
                "fecha_documento, metadatos, estado) VALUES "
                "(1, 1, 1, NULL, 'RECETA', 'Receta Carlos', 'Antiobiotico', "
                "'documentos/1/receta-carlos.pdf', '" + HASH_OK + "', 2, '2026-09-01', NULL, 'ACTIVO'),"
                "(2, 1, 1, NULL, 'RESULTADO_LAB', 'Resultado lab Carlos', NULL, "
                "'documentos/1/lab-carlos.pdf', '" + HASH_OK + "', 2, '2026-09-02', NULL, 'ACTIVO'),"
                "(3, 1, 2, NULL, 'RECETA', 'Receta Ana', NULL, "
                "'documentos/1/receta-ana.pdf', '" + HASH_OK + "', 2, '2026-09-03', NULL, 'ACTIVO'),"
                "(4, 2, 3, NULL, 'RECETA', 'Receta Luis', NULL, "
                "'documentos/2/receta-luis.pdf', '" + HASH_OK + "', 6, '2026-09-04', NULL, 'ACTIVO')"
            )

    def _seed_permisos(self, conn):
        # Matriz CU12: 6 permisos granulares documents:*
        conn.exec_driver_sql(
            "INSERT INTO permisos (id_permiso, nombre, descripcion, modulo, accion, estado) VALUES "
            "(1, 'documents:search', 'Buscar documentos', 'documents', 'search', 'ACTIVO'),"
            "(2, 'documents:download', 'Descargar documentos', 'documents', 'download', 'ACTIVO'),"
            "(3, 'documents:read:prescriptions', 'Leer recetas', 'documents', 'read', 'ACTIVO'),"
            "(4, 'documents:read:lab_orders', 'Leer ordenes lab', 'documents', 'read', 'ACTIVO'),"
            "(5, 'documents:read:lab_results', 'Leer resultados lab', 'documents', 'read', 'ACTIVO'),"
            "(6, 'documents:read:certificates', 'Leer certificados', 'documents', 'read', 'ACTIVO')"
        )
        # ADMIN=1, MEDICO=2 y PACIENTE=4 reciben los 6; RECEPCION=3 NO recibe lab_results (id 5)
        conn.exec_driver_sql(
            "INSERT INTO rol_permisos (id_rol, id_permiso) VALUES "
            "(1,1),(1,2),(1,3),(1,4),(1,5),(1,6),"
            "(2,1),(2,2),(2,3),(2,4),(2,5),(2,6),"
            "(3,1),(3,2),(3,3),(3,4),(3,6),"
            "(4,1),(4,2),(4,3),(4,4),(4,5),(4,6)"
        )

    def _override_current_user(self, user_id: int):
        def dependency():
            db: Session = self.SessionLocal()
            try:
                return db.get(Usuario, user_id)
            finally:
                db.close()

        app.dependency_overrides[get_current_user] = dependency

    def _count(self, sql: str) -> int:
        with self.engine.begin() as conn:
            return conn.exec_driver_sql(sql).fetchone()[0]

    def _create_payload(self, tipo: str = "RECETA", hash_hex: str = HASH_OK, **overrides) -> dict:
        payload = {
            "id_paciente": 1,
            "id_cita": None,
            "tipo_documento": tipo,
            "titulo": "Receta de prueba",
            "descripcion": "Tratamiento de prueba",
            "archivo_url": "documentos/1/prueba.pdf",
            "hash_archivo": hash_hex,
            "firmado_por": None,
            "fecha_documento": "2026-09-05",
            "metadatos": None,
        }
        payload.update(overrides)
        return payload

    # ------------------------------------------------------------------ #
    # Autenticación
    # ------------------------------------------------------------------ #
    def test_unauthenticated_gets_401(self):
        response = self.client.get("/api/v1/documentos")
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------ #
    # Aislamiento estricto multitenant
    # ------------------------------------------------------------------ #
    def test_admin_lists_only_own_tenant(self):
        self._override_current_user(1)
        response = self.client.get("/api/v1/documentos")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 3)
        self.assertTrue(all(item["id_clinica"] == 1 for item in body["items"]))

    def test_medico_otro_tenant_no_ve_documentos_ajenos(self):
        self._override_current_user(6)
        response = self.client.get("/api/v1/documentos")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["titulo"], "Receta Luis")

    def test_cross_tenant_detail_returns_404(self):
        self._override_current_user(6)
        response = self.client.get("/api/v1/documentos/1")
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_download_returns_404(self):
        self._override_current_user(6)
        response = self.client.get("/api/v1/documentos/1/download")
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------ #
    # RBAC recepción sin lectura de resultados de laboratorio
    # ------------------------------------------------------------------ #
    def test_recepcion_cannot_list_results_lab_403(self):
        self._override_current_user(3)
        response = self.client.get("/api/v1/documentos", params={"tipo_documento": "RESULTADO_LAB"})
        self.assertEqual(response.status_code, 403)

    def test_recepcion_can_list_recetas(self):
        self._override_current_user(3)
        response = self.client.get("/api/v1/documentos", params={"tipo_documento": "RECETA"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)

    def test_recepcion_detail_result_lab_403(self):
        self._override_current_user(3)
        response = self.client.get("/api/v1/documentos/2")
        self.assertEqual(response.status_code, 403)
        self.assertIn("RESULTADO_LAB", response.json()["detail"])

    # ------------------------------------------------------------------ #
    # Acceso del paciente a sus propios documentos
    # ------------------------------------------------------------------ #
    def test_paciente_me_solo_sus_documentos(self):
        self._override_current_user(4)
        response = self.client.get("/api/v1/documentos/me")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertTrue(all(item["id_paciente"] == 1 for item in body["items"]))

    def test_paciente_no_puede_leer_documento_ajeno(self):
        self._override_current_user(4)
        response = self.client.get("/api/v1/documentos/3")
        self.assertEqual(response.status_code, 404)

    def test_paciente_puede_listar_por_paciente_del_tenant(self):
        # El endpoint de documentos de un paciente no aplica a PACIENTE
        self._override_current_user(4)
        response = self.client.get("/api/v1/documentos", params={"tipo_documento": "RECETA"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)

    # ------------------------------------------------------------------ #
    # Creación / actualización / anulación
    # ------------------------------------------------------------------ #
    def test_medico_crea_documento_201(self):
        self._override_current_user(2)
        response = self.client.post("/api/v1/documentos", json=self._create_payload())
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["titulo"], "Receta de prueba")
        self.assertEqual(body["tipo_documento"], "RECETA")
        self.assertEqual(body["estado"], "ACTIVO")
        self.assertEqual(self._count("SELECT COUNT(*) FROM auditoria WHERE accion='CREAR_DOCUMENTO'"), 1)

    def test_recepcion_no_puede_crear_documento_403(self):
        self._override_current_user(3)
        response = self.client.post("/api/v1/documentos", json=self._create_payload())
        self.assertEqual(response.status_code, 403)

    def test_create_tipo_invalido_422(self):
        self._override_current_user(2)
        response = self.client.post(
            "/api/v1/documentos", json=self._create_payload(tipo="NOVEDAD")
        )
        self.assertEqual(response.status_code, 422)

    def test_create_hash_invalido_422(self):
        self._override_current_user(2)
        response = self.client.post(
            "/api/v1/documentos", json=self._create_payload(hash_hex="xyz")
        )
        self.assertEqual(response.status_code, 422)

    def test_admin_actualiza_metadata_200(self):
        self._override_current_user(1)
        response = self.client.put(
            "/api/v1/documentos/1",
            json={"titulo": "Receta Carlos actualizada", "descripcion": "Tratamiento extendido"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["titulo"], "Receta Carlos actualizada")

    def test_recepcion_no_puede_actualizar_403(self):
        self._override_current_user(3)
        response = self.client.put("/api/v1/documentos/1", json={"titulo": "X"})
        self.assertEqual(response.status_code, 403)

    def test_admin_anula_documento_200(self):
        self._override_current_user(1)
        response = self.client.delete("/api/v1/documentos/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estado"], "ANULADO")
        detail = self.client.get("/api/v1/documentos/1")
        self.assertEqual(detail.status_code, 404)

    def test_medico_no_puede_anular_403(self):
        self._override_current_user(2)
        response = self.client.delete("/api/v1/documentos/1")
        self.assertEqual(response.status_code, 403)

    def test_paciente_no_puede_acceder_a_me_sin_rol(self):
        # Un médico NO puede usar /me (solo PACIENTE)
        self._override_current_user(2)
        response = self.client.get("/api/v1/documentos/me")
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------ #
    # Descarga segura: auditoría y notificación
    # ------------------------------------------------------------------ #
    def test_download_returns_url_and_registers_audit(self):
        self._override_current_user(2)
        response = self.client.get("/api/v1/documentos/1/download")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["url_firmada"])
        self.assertLessEqual(body["expira_en"], 900)
        self.assertEqual(body["nombre_archivo"], "receta-carlos.pdf")
        self.assertEqual(
            self._count(
                "SELECT COUNT(*) FROM auditoria "
                "WHERE accion='DESCARGAR_DOCUMENTO' AND registro_id=1"
            ),
            1,
        )
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM notificaciones WHERE tipo='DOCUMENTO_DESCARGADO'"),
            1,
        )

    def test_download_requires_read_type_permission(self):
        # Recepción sin lab_results: download de un RESULTADO_LAB -> 403
        self._override_current_user(3)
        response = self.client.get("/api/v1/documentos/2/download")
        self.assertEqual(response.status_code, 403)

    def test_download_documento_inexistente_404(self):
        self._override_current_user(1)
        response = self.client.get("/api/v1/documentos/999/download")
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------ #
    # Listados por paciente y filtros
    # ------------------------------------------------------------------ #
    def test_medico_lista_documentos_de_paciente(self):
        self._override_current_user(2)
        response = self.client.get("/api/v1/pacientes/1/documentos")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertTrue(all(item["id_paciente"] == 1 for item in body["items"]))

    def test_paciente_inexistente_en_detalle_404(self):
        self._override_current_user(2)
        response = self.client.get("/api/v1/pacientes/999/documentos")
        self.assertEqual(response.status_code, 404)

    def test_paginacion(self):
        self._override_current_user(1)
        response = self.client.get("/api/v1/documentos", params={"page": 2, "page_size": 1})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["page"], 2)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["total_pages"], 3)

    def test_busqueda_por_titulo(self):
        self._override_current_user(1)
        response = self.client.get("/api/v1/documentos", params={"q": "Ana"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["titulo"], "Receta Ana")

    # ------------------------------------------------------------------ #
    # Servicio de archivos local y storage
    # ------------------------------------------------------------------ #
    def test_servir_archivo_local_y_storage_store(self):
        content = b"%PDF-1.4 mock document bytes"
        key, sha = storage_module.storage.store("mock-doc.pdf", content)
        self.assertEqual(key.startswith("documentos/"), True)
        self.assertEqual(len(sha), 64)

        self._override_current_user(1)
        url = f"/api/v1/documentos/file/{key}?nombre=mock-doc.pdf"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)
        self.assertTrue(response.headers["content-type"].startswith("application/pdf"))

        # Limpieza del archivo de prueba
        import pathlib

        file_path = (storage_module.storage.local_dir / key).resolve()
        if file_path.is_file():
            pathlib.Path(file_path).unlink()

    def test_storage_read_inexistente(self):
        self.assertEqual(storage_module.storage.read("documentos/zz/no-existe.pdf"), None)

    def test_file_endpoint_404_sin_archivo(self):
        self._override_current_user(1)
        response = self.client.get("/api/v1/documentos/file/documentos/zz/no-existe.pdf")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()