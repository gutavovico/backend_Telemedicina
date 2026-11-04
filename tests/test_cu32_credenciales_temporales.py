import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.models import Rol, Usuario
from app.modules.tenants.models import TenantRequest, TenantRequestTrackingAudit
from app.modules.tenants.public_onboarding.service import (
    get_tracking_status,
    reset_public_rate_limits,
)
from app.modules.tenants.tenant_management.schemas import ApproveRequest
from app.modules.tenants.tenant_management.service import approve_tenant_request


class TemporaryCredentialSecurityTestCase(unittest.TestCase):
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
        reset_public_rate_limits()
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM tenant_request_tracking_audits")
            conn.exec_driver_sql("DELETE FROM tenant_requests")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, id_clinica, nombre, estado) "
                "VALUES (1, NULL, 'SUPER ADMINISTRADOR', 'activo')"
            )
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, "
                "password_hash, estado, token_version, notificaciones_push, "
                "notificaciones_email, notificaciones_sms) VALUES "
                "(1, NULL, 1, 'Super', 'Admin', 'super@test.com', 'hash', 'activo', 0, 1, 1, 0)"
            )

    def _approve(self, suffix="1"):
        db = self.SessionLocal()
        request = TenantRequest(
            id_request=f"request-{suffix}",
            institucion_nombre=f"Clínica Segura {suffix}",
            nit=f"999{suffix}",
            correo=f"contacto{suffix}@test.com",
            responsable_nombre="Responsable Seguro",
            responsable_correo=f"admin{suffix}@test.com",
            tracking_code=f"TRK-SAFE-{suffix}",
            status="PENDING",
            row_version=1,
        )
        db.add(request)
        db.commit()
        super_admin = db.query(Usuario).filter(Usuario.id_usuario == 1).first()
        approve_tenant_request(db, super_admin, request.id_request, ApproveRequest(row_version=1))
        db.close()

    def test_approval_generates_random_credential_and_never_fixed_password(self):
        self._approve()
        db = self.SessionLocal()
        response = get_tracking_status(db, "TRK-SAFE-1")
        db.close()

        self.assertIsNotNone(response.temporary_password)
        self.assertNotEqual(response.temporary_password, "Temporal123!")
        self.assertGreaterEqual(len(response.temporary_password), 12)
        self.assertEqual(response.access_email, "admin1@test.com")
        self.assertEqual(response.remaining_reveals, 2)

    def test_credential_has_maximum_three_reveals_and_is_audited(self):
        self._approve()
        db = self.SessionLocal()
        first = get_tracking_status(db, "TRK-SAFE-1")
        second = get_tracking_status(db, "TRK-SAFE-1")
        third = get_tracking_status(db, "TRK-SAFE-1")
        fourth = get_tracking_status(db, "TRK-SAFE-1")
        audits = db.query(TenantRequestTrackingAudit).all()
        db.close()

        self.assertIsNotNone(first.temporary_password)
        self.assertIsNotNone(second.temporary_password)
        self.assertIsNotNone(third.temporary_password)
        self.assertIsNone(fourth.temporary_password)
        self.assertEqual(third.remaining_reveals, 0)
        self.assertTrue(any(a.accion == "REVELAR_CREDENCIAL_TEMPORAL" for a in audits))
        self.assertTrue(any(a.accion == "CONSULTAR_SEGUIMIENTO" for a in audits))
        self.assertNotIn("TRK-SAFE-1", " ".join(a.tracking_code_hash for a in audits))

    def test_expired_credential_is_not_revealed(self):
        self._approve()
        db = self.SessionLocal()
        request = db.query(TenantRequest).filter_by(id_request="request-1").first()
        request.temporary_password_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        response = get_tracking_status(db, "TRK-SAFE-1")
        db.close()

        self.assertIsNone(response.temporary_password)
        self.assertEqual(response.access_email, "admin1@test.com")

    def test_tracking_rate_limit_returns_429(self):
        self._approve()
        db = self.SessionLocal()
        status_code = None
        for _ in range(11):
            try:
                get_tracking_status(db, "TRK-SAFE-1", client_ip="192.0.2.10")
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                break
        db.close()
        self.assertEqual(status_code, 429)

    def test_temporary_password_is_single_use_and_change_is_mandatory(self):
        self._approve()
        db = self.SessionLocal()
        revealed = get_tracking_status(db, "TRK-SAFE-1")
        db.close()

        login = self.client.post(
            "/auth/login",
            json={"correo": "admin1@test.com", "password": revealed.temporary_password},
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["must_change_password"])
        token = login.json()["access_token"]

        protected = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(protected.status_code, 403)

        second_login = self.client.post(
            "/auth/login",
            json={"correo": "admin1@test.com", "password": revealed.temporary_password},
        )
        self.assertEqual(second_login.status_code, 401)

        changed = self.client.post(
            "/auth/change-temporary-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "nueva_password": "NuevaClaveSegura123!",
                "confirmar_password": "NuevaClaveSegura123!",
            },
        )
        self.assertEqual(changed.status_code, 200)

        final_login = self.client.post(
            "/auth/login",
            json={"correo": "admin1@test.com", "password": "NuevaClaveSegura123!"},
        )
        self.assertEqual(final_login.status_code, 200)
        self.assertFalse(final_login.json()["must_change_password"])


if __name__ == "__main__":
    unittest.main()
