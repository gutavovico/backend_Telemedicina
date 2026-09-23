import unittest
from datetime import date, datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Rol, Usuario, Permiso, RolPermiso
from app.modules.medical_records.models import Paciente, DocumentoClinico


class CU12DocumentosTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)

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

    def setUp(self):
        self._reset_data()
        self._seed_data()
        self._mock_user(self.user_admin)

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _mock_user(self, user: Usuario):
        app.dependency_overrides[get_current_user] = lambda: user

    def _reset_data(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM documentos_clinicos")
            conn.exec_driver_sql("DELETE FROM rol_permisos")
            conn.exec_driver_sql("DELETE FROM permisos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

    def _seed_data(self):
        db = self.SessionLocal()
        try:
            # Clinicas (Tenants)
            self.clinica_1 = Clinica(id_clinica=1, nombre="Clínica San Juan", estado="ACTIVO")
            self.clinica_2 = Clinica(id_clinica=2, nombre="Clínica del Norte", estado="ACTIVO")
            db.add_all([self.clinica_1, self.clinica_2])
            db.commit()

            # Roles
            self.rol_admin = Rol(id_rol=1, nombre="ADMIN", descripcion="Admin", id_clinica=1, estado="ACTIVO")
            self.rol_medico = Rol(id_rol=2, nombre="MEDICO", descripcion="Medico", id_clinica=1, estado="ACTIVO")
            self.rol_paciente = Rol(id_rol=4, nombre="PACIENTE", descripcion="Paciente", id_clinica=1, estado="ACTIVO")
            db.add_all([self.rol_admin, self.rol_medico, self.rol_paciente])
            db.commit()

            # Permisos
            permisos_nombres = [
                "documents:read:prescriptions",
                "documents:read:lab_orders",
                "documents:read:lab_results",
                "documents:read:certificates",
                "documents:download",
                "documents:search",
            ]
            self.permisos_map = {}
            for idx, p_name in enumerate(permisos_nombres, start=1):
                p = Permiso(id_permiso=idx, nombre=p_name, modulo="medical_records", accion=p_name, estado="ACTIVO")
                db.add(p)
                self.permisos_map[p_name] = p
            db.commit()

            # Asignar permisos al rol admin, medico y paciente
            for p in self.permisos_map.values():
                db.add(RolPermiso(id_rol=1, id_permiso=p.id_permiso))
                db.add(RolPermiso(id_rol=2, id_permiso=p.id_permiso))
                db.add(RolPermiso(id_rol=4, id_permiso=p.id_permiso))
            db.commit()

            # Usuarios
            self.user_admin = Usuario(
                id_usuario=1,
                id_clinica=1,
                id_rol=1,
                correo="admin@sanjuan.com",
                nombres="Admin",
                apellidos="San Juan",
                password_hash="hash",
                estado="ACTIVO",
            )
            self.user_paciente = Usuario(
                id_usuario=2,
                id_clinica=1,
                id_rol=4,
                correo="paciente@sanjuan.com",
                nombres="Carlos",
                apellidos="Mamani",
                password_hash="hash",
                estado="ACTIVO",
            )
            self.user_tenant2 = Usuario(
                id_usuario=3,
                id_clinica=2,
                id_rol=1,
                correo="admin@norte.com",
                nombres="Admin",
                apellidos="Norte",
                password_hash="hash",
                estado="ACTIVO",
            )
            db.add_all([self.user_admin, self.user_paciente, self.user_tenant2])
            db.commit()

            # Paciente
            self.paciente = Paciente(
                id_paciente=10,
                id_clinica=1,
                id_usuario=2,
                nombres="Carlos",
                apellidos="Mamani",
                ci="1234567",
                fecha_nacimiento=date(1990, 5, 20),
                genero="M",
                telefono="70012345",
                estado="ACTIVO",
            )
            db.add(self.paciente)
            db.commit()

            # Documentos clínicos en Tenant 1
            self.doc_receta = DocumentoClinico(
                id_documento=101,
                id_clinica=1,
                id_paciente=10,
                tipo_documento="RECETA",
                titulo="Receta Amoxicilina 500mg",
                descripcion="Tomar cada 8 horas por 7 dias",
                archivo_url="documentos/recetas/receta_101.pdf",
                hash_archivo="a" * 64,
                firmado_por=1,
                fecha_documento=date(2026, 9, 1),
                estado="ACTIVO",
            )
            self.doc_lab = DocumentoClinico(
                id_documento=102,
                id_clinica=1,
                id_paciente=10,
                tipo_documento="RESULTADO_LAB",
                titulo="Hemograma Completo",
                descripcion="Resultados normales",
                archivo_url="documentos/labs/lab_102.pdf",
                hash_archivo="b" * 64,
                firmado_por=1,
                fecha_documento=date(2026, 9, 2),
                estado="ACTIVO",
            )
            # Documento clínico en Tenant 2
            self.doc_tenant2 = DocumentoClinico(
                id_documento=201,
                id_clinica=2,
                id_paciente=None,
                tipo_documento="RECETA",
                titulo="Receta Tenant 2",
                descripcion="Privado de tenant 2",
                archivo_url="documentos/recetas/receta_201.pdf",
                hash_archivo="c" * 64,
                firmado_por=3,
                fecha_documento=date(2026, 9, 1),
                estado="ACTIVO",
            )
            db.add_all([self.doc_receta, self.doc_lab, self.doc_tenant2])
            db.commit()
        finally:
            db.close()

    def test_01_list_documents_tenant(self):
        """Admin lista documentos del tenant 1 y no ve los de tenant 2."""
        self._mock_user(self.user_admin)
        response = self.client.get(
            "/api/v1/documentos",
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        doc_ids = [item["id_documento"] for item in data["items"]]
        self.assertIn(101, doc_ids)
        self.assertIn(102, doc_ids)
        self.assertNotIn(201, doc_ids)

    def test_02_get_document_detail(self):
        """Obtiene el detalle de un documento clínico existente."""
        self._mock_user(self.user_admin)
        response = self.client.get(
            "/api/v1/documentos/101",
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id_documento"], 101)
        self.assertEqual(data["tipo_documento"], "RECETA")
        self.assertEqual(data["titulo"], "Receta Amoxicilina 500mg")

    def test_03_patient_my_documents(self):
        """Paciente autenticado consulta solo sus propios documentos vía /me."""
        self._mock_user(self.user_paciente)
        response = self.client.get(
            "/api/v1/documentos/me",
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)

    def test_04_create_document(self):
        """Admin/Médico registra un nuevo documento clínico en el tenant."""
        self._mock_user(self.user_admin)
        payload = {
            "id_paciente": 10,
            "tipo_documento": "ORDEN_LAB",
            "titulo": "Orden de Perfil Lipídico",
            "descripcion": "Ayuno 12 horas",
            "archivo_url": "documentos/ordenes/orden_103.pdf",
            "hash_archivo": "d" * 64,
            "fecha_documento": "2026-09-05",
        }
        response = self.client.post(
            "/api/v1/documentos",
            json=payload,
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["tipo_documento"], "ORDEN_LAB")
        self.assertEqual(data["id_clinica"], 1)

    def test_05_download_document_url(self):
        """Genera URL firmada de descarga para un documento existente."""
        self._mock_user(self.user_admin)
        response = self.client.get(
            "/api/v1/documentos/101/download",
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id_documento"], 101)
        self.assertTrue("url_firmada" in data)
        self.assertGreater(data["expira_en"], 0)

    def test_06_soft_delete_document(self):
        """Admin realiza anulación lógica de un documento clínico."""
        self._mock_user(self.user_admin)
        response = self.client.delete(
            "/api/v1/documentos/101",
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["estado"], "ANULADO")

        # Verificar que ya no aparece en listado activo
        get_resp = self.client.get("/api/v1/documentos/101", headers={"X-Tenant-ID": "1"})
        self.assertEqual(get_resp.status_code, 404)

    def test_07_multitenant_isolation(self):
        """Usuario del Tenant 1 no puede ver ni descargar documentos del Tenant 2 (404 Not Found)."""
        self._mock_user(self.user_admin)
        # Intentar acceder al documento 201 (perteneciente a clínica 2)
        response = self.client.get(
            "/api/v1/documentos/201",
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(response.status_code, 404)

        # Intentar descargar documento 201 desde Tenant 1
        dl_response = self.client.get(
            "/api/v1/documentos/201/download",
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(dl_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
