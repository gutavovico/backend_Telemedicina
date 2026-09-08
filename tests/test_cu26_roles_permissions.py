import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, joinedload
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


class CU26RolesPermissionsTestCase(unittest.TestCase):
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
            conn.exec_driver_sql("DELETE FROM rol_permisos")
            conn.exec_driver_sql("DELETE FROM permisos")
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
                 'hash-admin', NULL, 'activo', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (2, 1, 2, 'Doc', 'Uno', 'medico@telemedicina.com', '+59170000001',
                 'hash-medico', NULL, 'activo', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (3, 1, 3, 'Recep', 'Uno', 'recepcion@telemedicina.com', '+59170000002',
                 'hash-recepcion', NULL, 'activo', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (4, 1, 4, 'Pac', 'Uno', 'paciente@telemedicina.com', '+59170000003',
                 'hash-paciente', NULL, 'activo', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
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

    def _insert_permissions(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                """
                INSERT INTO permisos (id_permiso, nombre, descripcion, modulo, accion, estado) VALUES
                (1, 'VER_USUARIOS', 'Ver usuarios', 'users', 'read', 'ACTIVO'),
                (2, 'EDITAR_USUARIOS', 'Editar usuarios', 'users', 'write', 'ACTIVO'),
                (3, 'EXPORTAR_USUARIOS', 'Exportar usuarios', 'users', 'export', 'INACTIVO')
                """
            )

    def test_admin_can_list_roles(self):
        self._override_current_user(1)
        response = self.client.get("/roles")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 4)

    def test_admin_can_create_role(self):
        self._override_current_user(1)
        response = self.client.post(
            "/roles",
            json={
                "id_clinica": 1,
                "nombre": "Farmacia",
                "descripcion": "Rol farmacia",
                "estado": "ACTIVO",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["nombre"], "Farmacia")

    def test_admin_can_update_role(self):
        self._override_current_user(1)
        response = self.client.put(
            "/roles/2",
            json={
                "nombre": "Médico Senior",
                "descripcion": "Rol actualizado",
                "estado": "ACTIVO",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["nombre"], "Médico Senior")

    def test_admin_can_change_role_status(self):
        self._override_current_user(1)
        response = self.client.patch("/roles/2/status", json={"activo": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estado"], "INACTIVO")

    def test_admin_can_list_empty_permissions_catalog(self):
        self._override_current_user(1)
        response = self.client.get("/permissions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_admin_can_get_role_permissions(self):
        self._insert_permissions()
        with self.engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (1, 1), (1, 2)")

        self._override_current_user(1)
        response = self.client.get("/roles/1/permissions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_admin_can_assign_permissions(self):
        self._insert_permissions()
        self._override_current_user(1)
        response = self.client.put("/roles/1/permissions", json={"id_permisos": [1, 2]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id_permiso"] for item in response.json()], [1, 2])

    def test_unauthenticated_gets_401(self):
        response = self.client.get("/roles")
        self.assertEqual(response.status_code, 401)

    def test_medico_gets_403(self):
        self._override_current_user(2)
        response = self.client.get("/roles")
        self.assertEqual(response.status_code, 403)

    def test_recepcion_gets_403(self):
        self._override_current_user(3)
        response = self.client.get("/roles")
        self.assertEqual(response.status_code, 403)

    def test_paciente_gets_403(self):
        self._override_current_user(4)
        response = self.client.get("/roles")
        self.assertEqual(response.status_code, 403)

    def test_create_role_correctly(self):
        self._override_current_user(1)
        response = self.client.post(
            "/roles",
            json={"id_clinica": 1, "nombre": "Enfermería", "descripcion": "Rol enfermería"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["estado"], "ACTIVO")

    def test_duplicate_role_returns_409(self):
        self._override_current_user(1)
        response = self.client.post(
            "/roles",
            json={"nombre": "Administración", "descripcion": "Duplicado", "estado": "ACTIVO"},
        )
        self.assertEqual(response.status_code, 409)

    def test_get_existing_role(self):
        self._override_current_user(1)
        response = self.client.get("/roles/2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["nombre"], "Médico")

    def test_get_missing_role_returns_404(self):
        self._override_current_user(1)
        response = self.client.get("/roles/999")
        self.assertEqual(response.status_code, 404)

    def test_update_role(self):
        self._override_current_user(1)
        response = self.client.put(
            "/roles/3",
            json={"descripcion": "Recepción actualizada", "estado": "ACTIVO"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["descripcion"], "Recepción actualizada")

    def test_disable_role(self):
        self._override_current_user(1)
        response = self.client.patch("/roles/3/status", json={"activo": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estado"], "INACTIVO")

    def test_enable_role(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE roles SET estado = 'INACTIVO' WHERE id_rol = 3")

        self._override_current_user(1)
        response = self.client.patch("/roles/3/status", json={"activo": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estado"], "ACTIVO")

    def test_inactive_permission_is_not_assignable(self):
        self._insert_permissions()
        self._override_current_user(1)
        response = self.client.put("/roles/1/permissions", json={"id_permisos": [3]})
        self.assertEqual(response.status_code, 400)

    def test_permission_catalog_empty_is_supported(self):
        self._override_current_user(1)
        response = self.client.get("/roles/1/permissions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_assign_permissions(self):
        self._insert_permissions()
        self._override_current_user(1)
        response = self.client.put("/roles/1/permissions", json={"id_permisos": [1, 2]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_get_assigned_permissions(self):
        self._insert_permissions()
        with self.engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (2, 1)")

        self._override_current_user(1)
        response = self.client.get("/roles/2/permissions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id_permiso"], 1)

    def test_remove_permissions(self):
        self._insert_permissions()
        with self.engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO rol_permisos (id_rol, id_permiso) VALUES (1, 1), (1, 2)")

        self._override_current_user(1)
        response = self.client.put("/roles/1/permissions", json={"id_permisos": [2]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id_permiso"] for item in response.json()], [2])

    def test_duplicate_permission_ids_do_not_duplicate_relations(self):
        self._insert_permissions()
        self._override_current_user(1)
        response = self.client.put("/roles/1/permissions", json={"id_permisos": [1, 1, 2, 2]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id_permiso"] for item in response.json()], [1, 2])

        with self.engine.begin() as conn:
            count = conn.exec_driver_sql("SELECT COUNT(*) FROM rol_permisos WHERE id_rol = 1").scalar_one()
        self.assertEqual(count, 2)

    def test_nonexistent_permission_returns_404(self):
        self._insert_permissions()
        self._override_current_user(1)
        response = self.client.put("/roles/1/permissions", json={"id_permisos": [99]})
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_role_for_permission_assignment_returns_404(self):
        self._insert_permissions()
        self._override_current_user(1)
        response = self.client.put("/roles/999/permissions", json={"id_permisos": [1]})
        self.assertEqual(response.status_code, 404)

    def test_inactive_role_cannot_receive_permissions(self):
        self._insert_permissions()
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE roles SET estado = 'INACTIVO' WHERE id_rol = 2")

        self._override_current_user(1)
        response = self.client.put("/roles/2/permissions", json={"id_permisos": [1]})
        self.assertEqual(response.status_code, 400)

    def test_openapi_contains_role_endpoints(self):
        self._override_current_user(1)
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/roles", paths)
        self.assertIn("/roles/{id_rol}", paths)
        self.assertIn("/roles/{id_rol}/status", paths)
        self.assertIn("/permissions", paths)
        self.assertIn("/roles/{id_rol}/permissions", paths)


if __name__ == "__main__":
    unittest.main()
