import unittest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import joinedload, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Rol, Usuario, Auditoria
from app.modules.auth.audit.service import registrar_evento, sanitize_payload


class CU21AuditoriaTestCase(unittest.TestCase):
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
        self._mock_user(10)

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _mock_user(self, user_id: int):
        def _get_user():
            db = self.SessionLocal()
            try:
                u = db.query(Usuario).options(joinedload(Usuario.rol)).filter(Usuario.id_usuario == user_id).first()
                if u:
                    db.expunge_all()
                return u
            finally:
                db.close()

        app.dependency_overrides[get_current_user] = _get_user

    def _reset_data(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM auditoria")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

    def _seed_data(self):
        db = self.SessionLocal()
        try:
            self.clinica1 = Clinica(
                id_clinica=1,
                nombre="Clínica San Juan",
                estado="ACTIVO"
            )
            self.clinica2 = Clinica(
                id_clinica=2,
                nombre="Clínica Los Andes",
                estado="ACTIVO"
            )
            db.add_all([self.clinica1, self.clinica2])

            self.rol_admin = Rol(id_rol=1, nombre="ADMINISTRADOR", descripcion="Admin del sistema")
            self.rol_auditor = Rol(id_rol=2, nombre="AUDITOR", descripcion="Auditor de registros")
            self.rol_paciente = Rol(id_rol=3, nombre="PACIENTE", descripcion="Paciente regular")
            db.add_all([self.rol_admin, self.rol_auditor, self.rol_paciente])
            db.flush()

            self.user_admin = Usuario(
                id_usuario=10,
                id_clinica=1,
                id_rol=1,
                correo="admin@sanjuan.com",
                password_hash="fakehash",
                nombres="Carlos",
                apellidos="Admin",
                estado="ACTIVO",
                token_version=0
            )
            self.user_auditor = Usuario(
                id_usuario=11,
                id_clinica=1,
                id_rol=2,
                correo="auditor@sanjuan.com",
                password_hash="fakehash",
                nombres="Ana",
                apellidos="Auditora",
                estado="ACTIVO",
                token_version=0
            )
            self.user_admin2 = Usuario(
                id_usuario=20,
                id_clinica=2,
                id_rol=1,
                correo="admin@losandes.com",
                password_hash="fakehash",
                nombres="Roberto",
                apellidos="Admin2",
                estado="ACTIVO",
                token_version=0
            )
            self.user_paciente = Usuario(
                id_usuario=30,
                id_clinica=1,
                id_rol=3,
                correo="paciente@sanjuan.com",
                password_hash="fakehash",
                nombres="Pedro",
                apellidos="Pérez",
                estado="ACTIVO",
                token_version=0
            )
            db.add_all([self.user_admin, self.user_auditor, self.user_admin2, self.user_paciente])
            db.commit()
        finally:
            db.close()

    def test_list_audit_logs_empty(self):
        """Verifica listar bitácora cuando no hay eventos registrados."""
        res = self.client.get("/api/v1/audit-log", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["data"], [])

    def test_registrar_and_list_audit_logs(self):
        """Verifica inserción inmutable con registrar_evento y su consulta en el endpoint."""
        db = self.SessionLocal()
        try:
            registrar_evento(
                db=db,
                id_usuario=10,
                id_clinica=1,
                accion="LOGIN",
                descripcion="Inicio de sesión exitoso del administrador",
                direccion_ip="192.168.1.50"
            )
            registrar_evento(
                db=db,
                id_usuario=10,
                id_clinica=1,
                accion="INSERT",
                tabla_afectada="pacientes",
                registro_id=101,
                descripcion="Registro de nuevo paciente",
                datos_nuevos={"ci": "1234567", "nombres": "Juan"},
                direccion_ip="192.168.1.50"
            )
        finally:
            db.close()

        res = self.client.get("/api/v1/audit-log", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["data"]), 2)
        acciones = [entry["accion"] for entry in data["data"]]
        self.assertIn("LOGIN", acciones)
        self.assertIn("INSERT", acciones)

    def test_filter_audit_logs(self):
        """Verifica filtrado por acción, tabla y búsqueda textual."""
        db = self.SessionLocal()
        try:
            registrar_evento(
                db=db,
                id_usuario=10,
                id_clinica=1,
                accion="UPDATE",
                tabla_afectada="usuarios",
                registro_id=5,
                descripcion="Cambio de estado de usuario"
            )
            registrar_evento(
                db=db,
                id_usuario=10,
                id_clinica=1,
                accion="DELETE",
                tabla_afectada="roles",
                registro_id=8,
                descripcion="Eliminación lógica de rol secundario"
            )
        finally:
            db.close()

        # Filtro por acción
        res = self.client.get("/api/v1/audit-log?accion=UPDATE", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["data"][0]["accion"], "UPDATE")

        # Filtro por tabla afectada
        res_tabla = self.client.get("/api/v1/audit-log?tabla_afectada=roles", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res_tabla.status_code, 200)
        self.assertEqual(res_tabla.json()["total"], 1)
        self.assertEqual(res_tabla.json()["data"][0]["tabla_afectada"], "roles")

    def test_get_audit_log_detail(self):
        """Verifica la consulta de detalle de un registro por ID."""
        db = self.SessionLocal()
        try:
            ev = registrar_evento(
                db=db,
                id_usuario=10,
                id_clinica=1,
                accion="SELECT",
                tabla_afectada="historias_clinicas",
                registro_id=42,
                descripcion="Acceso al expediente del paciente",
                direccion_ip="10.0.0.1"
            )
            ev_id = ev.id_auditoria
        finally:
            db.close()

        res = self.client.get(f"/api/v1/audit-log/{ev_id}", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res.status_code, 200)
        detail = res.json()
        self.assertEqual(detail["id_auditoria"], ev_id)
        self.assertEqual(detail["accion"], "SELECT")
        self.assertEqual(detail["tabla_afectada"], "historias_clinicas")
        self.assertEqual(detail["registro_id"], 42)

    def test_audit_multitenant_isolation(self):
        """Verifica el aislamiento estricto entre clínicas: tenant 2 no ve registros de tenant 1."""
        db = self.SessionLocal()
        try:
            ev1 = registrar_evento(
                db=db,
                id_usuario=10,
                id_clinica=1,
                accion="LOGIN",
                descripcion="Login clínica 1"
            )
            ev2 = registrar_evento(
                db=db,
                id_usuario=20,
                id_clinica=2,
                accion="LOGIN",
                descripcion="Login clínica 2"
            )
            ev1_id = ev1.id_auditoria
        finally:
            db.close()

        # Admin de clínica 2 consulta listado
        self._mock_user(20)
        res = self.client.get("/api/v1/audit-log", headers={"X-Tenant-ID": "2"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["data"][0]["id_clinica"], 2)

        # Admin de clínica 2 intenta acceder por ID a un registro de clínica 1 -> 404
        res_cross = self.client.get(f"/api/v1/audit-log/{ev1_id}", headers={"X-Tenant-ID": "2"})
        self.assertEqual(res_cross.status_code, 404)

    def test_export_pdf_and_excel(self):
        """Verifica exportación a PDF y Excel."""
        db = self.SessionLocal()
        try:
            registrar_evento(
                db=db,
                id_usuario=10,
                id_clinica=1,
                accion="INSERT",
                tabla_afectada="citas",
                descripcion="Creación de cita"
            )
        finally:
            db.close()

        res_pdf = self.client.get("/api/v1/audit-log/export/pdf", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf.headers["content-type"], "application/pdf")

        res_excel = self.client.get("/api/v1/audit-log/export/excel", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res_excel.status_code, 200)

    def test_audit_log_immutability(self):
        """
        Garantiza la inalterabilidad absoluta (RN-CU21-01):
        Cualquier intento de mutar o eliminar registros de auditoría vía HTTP es rechazado con 405 Method Not Allowed.
        """
        # Intentar POST
        res_post = self.client.post("/api/v1/audit-log", json={"accion": "HACK"})
        self.assertEqual(res_post.status_code, 405)

        # Intentar PUT
        res_put = self.client.put("/api/v1/audit-log/1", json={"accion": "HACK"})
        self.assertEqual(res_put.status_code, 405)

        # Intentar PATCH
        res_patch = self.client.patch("/api/v1/audit-log/1", json={"accion": "HACK"})
        self.assertEqual(res_patch.status_code, 405)

        # Intentar DELETE
        res_del = self.client.delete("/api/v1/audit-log/1")
        self.assertEqual(res_del.status_code, 405)

    def test_sanitize_payload(self):
        """Verifica la sanitización de claves sensibles como contraseñas y tokens."""
        payload = {
            "usuario": "doctor",
            "password": "SecretPassword123",
            "token": "jwt.secret.token",
            "nested": {
                "access_token": "bearer123",
                "datos": "visibles"
            }
        }
        sanitized = sanitize_payload(payload)
        self.assertEqual(sanitized["password"], "[PROTEGIDO]")
        self.assertEqual(sanitized["token"], "[PROTEGIDO]")
        self.assertEqual(sanitized["nested"]["access_token"], "[PROTEGIDO]")
        self.assertEqual(sanitized["nested"]["datos"], "visibles")
        self.assertEqual(sanitized["usuario"], "doctor")


if __name__ == "__main__":
    unittest.main()
