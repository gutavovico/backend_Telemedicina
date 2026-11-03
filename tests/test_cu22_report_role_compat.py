"""CU22 authorization against the current Usuario.rol / rol_rel shape."""

import unittest

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.modules.analytics.reportes.router import router
from app.modules.analytics.reportes.dependencies import require_report_admin
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Rol, Usuario
from app.modules.medical_records import models as medical_record_models  # noqa: F401; mapper registry


class ReportRoleCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE clinicas (id_clinica INTEGER PRIMARY KEY, estado TEXT)"
            )
            connection.exec_driver_sql(
                "INSERT INTO clinicas VALUES (1, 'ACTIVO'), (2, 'ACTIVO')"
            )
        session_factory = sessionmaker(bind=self.engine)
        self.app = FastAPI()
        self.app.include_router(router)

        @self.app.get("/scope")
        def scope(clinic_id: int = Depends(require_report_admin)):
            return {"id_clinica": clinic_id}

        def local_db():
            with session_factory() as session:
                yield session

        self.app.dependency_overrides[get_db] = local_db
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    @staticmethod
    def user_with_role(name="ADMIN", *, clinic=1, role_clinic=1,
                       role_state="ACTIVO", user_state="ACTIVO"):
        user = Usuario(id_clinica=clinic, estado=user_state)
        user.rol_rel = Rol(nombre=name, id_clinica=role_clinic, estado=role_state)
        return user

    def test_current_role_name_and_relation_allow_active_admin(self):
        self.user = self.user_with_role()
        self.assertEqual(self.user.rol, "ADMIN")
        response = self.client.get("/analytics/reportes/catalogo")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("reportes", response.json())

    def test_other_roles_and_invalid_relations_are_forbidden(self):
        users = (
            self.user_with_role("MEDICO"),
            self.user_with_role(role_state="INACTIVO"),
            self.user_with_role(user_state="INACTIVO"),
            self.user_with_role(role_clinic=2),
            Usuario(id_clinica=1, estado="ACTIVO"),
        )
        for self.user in users:
            with self.subTest(role=self.user.rol, clinic=self.user.id_clinica):
                response = self.client.get("/analytics/reportes/catalogo")
                self.assertEqual(response.status_code, 403, response.text)

    def test_header_cannot_change_authenticated_clinic(self):
        self.user = self.user_with_role(clinic=2, role_clinic=2)
        response = self.client.get("/scope", headers={"X-Tenant-ID": "1"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"id_clinica": 2})


if __name__ == "__main__":
    unittest.main()
