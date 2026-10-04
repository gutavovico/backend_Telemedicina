"""Lectura del rol propio sin acceso al catálogo (CU05 recepción)."""
import unittest

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


class RolPropioTestCase(unittest.TestCase):
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
            for table in ("rol_permisos", "usuarios", "roles", "clinicas"):
                conn.exec_driver_sql(f"DELETE FROM {table}")
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'Clínica Uno', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, id_clinica, nombre, descripcion, estado) VALUES "
                "(1, 1, 'ADMIN', 'Admin', 'activo'), "
                "(3, 1, 'RECEPCION', 'Recepción', 'activo')"
            )
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, "
                "correo, password_hash, estado, token_version, notificaciones_push, "
                "notificaciones_email, notificaciones_sms) VALUES "
                "(1, 1, 1, 'Admin', 'Uno', 'admin1@test.com', 'hash', 'activo', 0, 1, 1, 0), "
                "(2, 1, 3, 'Recep', 'Uno', 'recep1@test.com', 'hash', 'activo', 0, 1, 1, 0)"
            )

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _as_user(self, id_usuario: int):
        def current_user(db: Session = Depends(get_db)):
            return db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()

        app.dependency_overrides[get_current_user] = current_user

    def test_recepcion_lee_su_propio_rol(self):
        self._as_user(2)
        resp = self.client.get("/roles/3")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["nombre"], "RECEPCION")

    def test_recepcion_no_lee_rol_ajeno_ni_catalogo(self):
        self._as_user(2)
        self.assertEqual(self.client.get("/roles/1").status_code, 403)
        self.assertEqual(self.client.get("/roles").status_code, 403)

    def test_admin_sigue_viendo_todo(self):
        self._as_user(1)
        self.assertEqual(self.client.get("/roles/3").status_code, 200)
        self.assertEqual(self.client.get("/roles").status_code, 200)


if __name__ == "__main__":
    unittest.main()
