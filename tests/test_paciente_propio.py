"""Detalle de paciente: el paciente ve solo su registro (CU28 criterio 8)."""
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


class PacientePropioTestCase(unittest.TestCase):
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
            for table in ("auditoria", "pacientes", "usuarios", "roles", "clinicas"):
                conn.exec_driver_sql(f"DELETE FROM {table}")
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'Clínica Uno', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES "
                "(1, 1, 'ADMIN', 'activo'), (4, 1, 'PACIENTE', 'activo')"
            )
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, "
                "correo, password_hash, estado, token_version, notificaciones_push, "
                "notificaciones_email, notificaciones_sms) VALUES "
                "(1, 1, 1, 'Admin', 'Uno', 'admin1@test.com', 'hash', 'activo', 0, 1, 1, 0), "
                "(10, 1, 4, 'Ana', 'Uno', 'ana1@test.com', 'hash', 'activo', 0, 1, 1, 0), "
                "(11, 1, 4, 'Luis', 'Uno', 'luis1@test.com', 'hash', 'activo', 0, 1, 1, 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO pacientes (id_paciente, id_clinica, id_usuario, nombres, apellidos, "
                "ci, fecha_nacimiento, genero, telefono, estado) VALUES "
                "(1, 1, 10, 'Ana', 'Uno', '111', '1990-01-01', 'F', '700', 'ACTIVO'), "
                "(2, 1, 11, 'Luis', 'Uno', '222', '1991-02-02', 'M', '701', 'ACTIVO')"
            )

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _as_user(self, id_usuario: int):
        def current_user(db: Session = Depends(get_db)):
            return db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()

        app.dependency_overrides[get_current_user] = current_user

    def test_paciente_ve_su_propio_registro(self):
        self._as_user(10)
        resp = self.client.get("/api/v1/pacientes/1")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["id_paciente"], 1)

    def test_paciente_no_ve_registro_ajeno(self):
        self._as_user(10)
        resp = self.client.get("/api/v1/pacientes/2")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_admin_sigue_viendo_todo(self):
        self._as_user(1)
        self.assertEqual(self.client.get("/api/v1/pacientes/1").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/pacientes/2").status_code, 200)


if __name__ == "__main__":
    unittest.main()
