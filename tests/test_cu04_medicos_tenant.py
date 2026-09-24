"""Aislamiento multitenant del CU04: perfiles médicos y matrículas."""
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


class CU04MedicosTenantTestCase(unittest.TestCase):
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
            conn.exec_driver_sql("DELETE FROM medico_especialidad")
            conn.exec_driver_sql("DELETE FROM medicos")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")
            conn.exec_driver_sql("INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'Clínica Uno', 'ACTIVO'), (2, 'Clínica Dos', 'ACTIVO')")
            conn.exec_driver_sql("INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES (1, 1, 'ADMIN', 'activo'), (2, 1, 'MEDICO', 'activo'), (3, 2, 'ADMIN', 'activo'), (4, 2, 'MEDICO', 'activo')")
            conn.exec_driver_sql("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, token_version, notificaciones_push, notificaciones_email, notificaciones_sms)
                VALUES
                  (1, 1, 1, 'Admin', 'Uno', 'admin1@test.com', 'hash', 'activo', 0, 1, 1, 0),
                  (2, 1, 2, 'Médico', 'Uno', 'medico1@test.com', 'hash', 'activo', 0, 1, 1, 0),
                  (3, 2, 3, 'Admin', 'Dos', 'admin2@test.com', 'hash', 'activo', 0, 1, 1, 0),
                  (4, 2, 4, 'Médico', 'Dos', 'medico2@test.com', 'hash', 'activo', 0, 1, 1, 0),
                  (5, NULL, 1, 'Admin', 'Sin Clínica', 'admin-sin-clinica@test.com', 'hash', 'activo', 0, 1, 1, 0)
            """)

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _as_user(self, id_usuario: int):
        def current_user(db: Session = Depends(get_db)):
            return db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()
        app.dependency_overrides[get_current_user] = current_user

    @staticmethod
    def _payload(id_usuario: int):
        return {"id_usuario": id_usuario, "matricula_profesional": "BOL-1234"}

    def test_perfiles_y_matriculas_se_aislan_por_clinica(self):
        self._as_user(1)
        creada_uno = self.client.post("/medicos", json=self._payload(2))
        self.assertEqual(creada_uno.status_code, 201, creada_uno.text)
        medico_uno = creada_uno.json()
        self.assertEqual(medico_uno["tenant_id"], "1")

        # La misma matrícula es válida en otra clínica y el perfil ajeno no se expone.
        self._as_user(3)
        self.assertEqual(self.client.get(f"/medicos/{medico_uno['id_medico']}").status_code, 404)
        creada_dos = self.client.post("/medicos", json=self._payload(4))
        self.assertEqual(creada_dos.status_code, 201, creada_dos.text)
        self.assertEqual(creada_dos.json()["tenant_id"], "2")

        # Un administrador no puede crear un perfil para un usuario de otra clínica.
        cross_tenant = self.client.post("/medicos", json=self._payload(2))
        self.assertEqual(cross_tenant.status_code, 404)

    def test_header_no_concede_un_tenant_a_usuario_sin_clinica(self):
        self._as_user(5)
        respuesta = self.client.get("/medicos", headers={"X-Tenant-ID": "1"})
        self.assertEqual(respuesta.status_code, 403)


if __name__ == "__main__":
    unittest.main()
