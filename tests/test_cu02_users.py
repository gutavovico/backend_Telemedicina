import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker, joinedload
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import hash_password
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


class CU02UsersTestCase(unittest.TestCase):
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
        from app.core.database import Base
        import app.modules.auth.models
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self._reset_data()

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _reset_data(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'Clinica Central', 'ACTIVO'), (2, 'Clinica Norte', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                """
                INSERT INTO roles (id_rol, id_clinica, nombre, descripcion, estado) VALUES
                (1, NULL, 'Administración', 'Admin global', 'ACTIVO'),
                (2, NULL, 'Médico', 'Rol médico', 'ACTIVO'),
                (3, NULL, 'Recepción', 'Rol recepción', 'ACTIVO'),
                (4, NULL, 'Paciente', 'Rol paciente', 'ACTIVO')
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO usuarios (
                    id_usuario, id_clinica, id_rol, nombres, apellidos, correo, telefono,
                    password_hash, foto_perfil, estado, notificaciones_push,
                    notificaciones_email, notificaciones_sms, fecha_creacion, fecha_actualizacion
                ) VALUES
                (1, 1, 1, 'Admin', 'Sistema', 'admin@telemedicina.com', '+59170000000',
                 :admin_hash, NULL, 'activo', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (2, 1, 2, 'Doc', 'Uno', 'medico@telemedicina.com', '+59170000001',
                 :med_hash, NULL, 'activo', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (3, 1, 3, 'Recep', 'Uno', 'recepcion@telemedicina.com', '+59170000002',
                 :rec_hash, NULL, 'activo', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (4, 1, 4, 'Pac', 'Uno', 'paciente@telemedicina.com', '+59170000003',
                 :pac_hash, NULL, 'activo', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                {
                    "admin_hash": hash_password("admin123"),
                    "med_hash": hash_password("medico123"),
                    "rec_hash": hash_password("recepcion123"),
                    "pac_hash": hash_password("paciente123"),
                },
            )

    def _override_current_user(self, user_id: int):
        def dependency():
            db: Session = self.SessionLocal()
            try:
                return (
                    db.query(Usuario)
                    .options(joinedload(Usuario.rol))
                    .filter(Usuario.id_usuario == user_id)
                    .first()
                )
            finally:
                db.close()

        app.dependency_overrides[get_current_user] = dependency

    def test_admin_can_list_users(self):
        self._override_current_user(1)
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 4)
        self.assertNotIn("password_hash", data[0])

    def test_unauthenticated_user_gets_401(self):
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 401)

    def test_medico_gets_403(self):
        self._override_current_user(2)
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 403)

    def test_recepcion_gets_403(self):
        self._override_current_user(3)
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 403)

    def test_paciente_gets_403(self):
        self._override_current_user(4)
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 403)

    def test_get_existing_user(self):
        self._override_current_user(1)
        response = self.client.get("/users/2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["correo"], "medico@telemedicina.com")

    def test_get_missing_user_returns_404(self):
        self._override_current_user(1)
        response = self.client.get("/users/999")
        self.assertEqual(response.status_code, 404)

    def test_create_user(self):
        self._override_current_user(1)
        payload = {
            "id_clinica": 1,
            "id_rol": 2,
            "nombres": "Nuevo",
            "apellidos": "Usuario",
            "correo": "nuevo@telemedicina.com",
            "telefono": "+59179999999",
            "password": "NuevaPass123",
            "estado": "activo",
            "notificaciones_push": True,
            "notificaciones_email": True,
            "notificaciones_sms": False,
        }
        response = self.client.post("/users", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["id_rol"], 2)
        self.assertEqual(data["nombre_rol"], "Médico")
        self.assertNotIn("password_hash", data)

        with self.SessionLocal() as db:
            created = db.execute(
                text("SELECT password_hash FROM usuarios WHERE correo = :correo"),
                {"correo": "nuevo@telemedicina.com"},
            ).scalar_one()
        self.assertNotEqual(created, "NuevaPass123")

    def test_duplicate_email_returns_409(self):
        self._override_current_user(1)
        payload = {
            "id_clinica": 1,
            "id_rol": 2,
            "nombres": "Otro",
            "apellidos": "Usuario",
            "correo": "medico@telemedicina.com",
            "password": "NuevaPass123",
            "estado": "activo",
            "notificaciones_push": True,
            "notificaciones_email": True,
            "notificaciones_sms": False,
        }
        response = self.client.post("/users", json=payload)
        self.assertEqual(response.status_code, 409)

    def test_missing_role_returns_404(self):
        self._override_current_user(1)
        payload = {
            "id_clinica": 1,
            "id_rol": 99,
            "nombres": "Otro",
            "apellidos": "Usuario",
            "correo": "otro@telemedicina.com",
            "password": "NuevaPass123",
            "estado": "activo",
            "notificaciones_push": True,
            "notificaciones_email": True,
            "notificaciones_sms": False,
        }
        response = self.client.post("/users", json=payload)
        self.assertEqual(response.status_code, 404)

    def test_update_user(self):
        self._override_current_user(1)
        payload = {
            "nombres": "Medico Actualizado",
            "correo": "medico.actualizado@telemedicina.com",
            "id_clinica": 1,
            "id_rol": 2,
            "password": "MedicoNuevo123",
        }
        response = self.client.put("/users/2", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["nombres"], "Medico Actualizado")
        self.assertEqual(data["correo"], "medico.actualizado@telemedicina.com")

        with self.SessionLocal() as db:
            updated = db.get(Usuario, 2)
            self.assertNotEqual(updated.password_hash, "MedicoNuevo123")

    def test_disable_user(self):
        self._override_current_user(1)
        response = self.client.patch("/users/2/status", json={"activo": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estado"], "inactivo")

    def test_enable_user(self):
        with self.SessionLocal() as db:
            user = db.get(Usuario, 2)
            user.estado = "inactivo"
            db.add(user)
            db.commit()

        self._override_current_user(1)
        response = self.client.patch("/users/2/status", json={"activo": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estado"], "activo")

    def test_disabled_user_cannot_authenticate(self):
        with self.SessionLocal() as db:
            user = db.get(Usuario, 2)
            user.estado = "inactivo"
            db.add(user)
            db.commit()

        response = self.client.post(
            "/auth/login",
            json={"correo": "medico@telemedicina.com", "password": "medico123"},
        )
        self.assertEqual(response.status_code, 403)

    def test_openapi_contains_users_paths(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/users", paths)
        self.assertIn("/users/{id_usuario}", paths)
        self.assertIn("/users/{id_usuario}/status", paths)

    def test_auth_login_still_works_for_admin(self):
        response = self.client.post(
            "/auth/login",
            json={"correo": "admin@telemedicina.com", "password": "admin123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())

    def test_auth_register_still_works(self):
        response = self.client.post(
            "/auth/register",
            json={
                "nombres": "Registro",
                "apellidos": "Publico",
                "correo": "registro@telemedicina.com",
                "password": "Registro123",
                "telefono": "+59175555555",
                "notificaciones_push": True,
                "notificaciones_email": True,
                "notificaciones_sms": False,
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["correo"], "registro@telemedicina.com")
        self.assertNotIn("password_hash", data)

    def test_auth_me_still_works(self):
        self._override_current_user(1)
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["correo"], "admin@telemedicina.com")
        self.assertEqual(response.json()["rol"], "Administración")


if __name__ == "__main__":
    unittest.main()
