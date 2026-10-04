"""Endpoints SaaS de clínicas: lista, estado (superadmin) y registro público."""
import unittest

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Rol, Usuario


class ClinicasTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
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
        with self.engine.begin() as conn:
            for table in ("auditoria", "usuarios", "roles", "clinicas"):
                conn.exec_driver_sql(f"DELETE FROM {table}")
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES "
                "(1, 'Clínica Uno', 'ACTIVO'), (2, 'Clínica Dos', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES "
                "(1, 1, 'ADMIN', 'activo'), "
                "(90, NULL, 'Super Administrador', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, "
                "correo, password_hash, estado, token_version, notificaciones_push, "
                "notificaciones_email, notificaciones_sms) VALUES "
                "(1, 1, 1, 'Admin', 'Uno', 'admin1@test.com', 'hash', 'activo', 0, 1, 1, 0), "
                "(100, NULL, 90, 'Super', 'Admin', 'super@test.com', 'hash', 'activo', 0, 1, 1, 0)"
            )

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _as_user(self, id_usuario: int):
        def current_user(db: Session = Depends(get_db)):
            return db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()

        app.dependency_overrides[get_current_user] = current_user

    def test_superadmin_lista_clinicas(self):
        self._as_user(100)
        resp = self.client.get("/api/v1/clinicas")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["total"], 2)

    def test_admin_tenant_no_lista(self):
        self._as_user(1)
        resp = self.client.get("/api/v1/clinicas")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_sin_auth_no_lista(self):
        resp = self.client.get("/api/v1/clinicas")
        self.assertIn(resp.status_code, (401, 403))

    def test_superadmin_cambia_estado_y_filtra(self):
        self._as_user(100)
        resp = self.client.patch("/api/v1/clinicas/2/estado", json={"estado": "SUSPENDIDO"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["estado"], "SUSPENDIDO")

        filtrado = self.client.get("/api/v1/clinicas", params={"estado": "SUSPENDIDO"})
        self.assertEqual(filtrado.status_code, 200)
        self.assertEqual(filtrado.json()["total"], 1)

    def test_estado_invalido_422_y_no_existe_404(self):
        self._as_user(100)
        self.assertEqual(
            self.client.patch("/api/v1/clinicas/1/estado", json={"estado": "RARO"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.patch("/api/v1/clinicas/999/estado", json={"estado": "ACTIVO"}).status_code,
            404,
        )

    def test_admin_tenant_no_cambia_estado(self):
        self._as_user(1)
        resp = self.client.patch("/api/v1/clinicas/2/estado", json={"estado": "INACTIVO"})
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_registro_publico_crea_clinica_y_admin(self):
        payload = {
            "nombre": "Clínica Tres",
            "nit": "NIT-003",
            "admin_nombres": "Ana",
            "admin_apellidos": "Tres",
            "admin_email": "admin3@test.com",
            "admin_password": "secreta123",
        }
        resp = self.client.post("/api/v1/clinicas/registrar", json=payload)
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["clinica"]["estado"], "ACTIVO")
        self.assertEqual(body["administrador"]["correo"], "admin3@test.com")

        # Email duplicado y NIT duplicado se rechazan.
        dup_email = dict(payload, nombre="Otra", nit="NIT-004")
        self.assertEqual(
            self.client.post("/api/v1/clinicas/registrar", json=dup_email).status_code, 400
        )
        dup_nit = dict(payload, nombre="Otra", admin_email="otro@test.com")
        self.assertEqual(
            self.client.post("/api/v1/clinicas/registrar", json=dup_nit).status_code, 400
        )


if __name__ == "__main__":
    unittest.main()
