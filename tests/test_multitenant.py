import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.core.services.base_service import TenantAwareService
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Permiso, Rol, RolPermiso, Usuario, Auditoria
from app.modules.medical_records.models import Paciente


class MultitenantBackendTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=cls.engine)

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
        self._seed_data()

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _seed_data(self):
        db = self.SessionLocal()
        try:
            db.query(RolPermiso).delete()
            db.query(Permiso).delete()
            db.query(Paciente).delete()
            db.query(Auditoria).delete()
            db.query(Usuario).delete()
            db.query(Rol).delete()
            db.query(Clinica).delete()
            db.commit()

            # 1. Clinicas
            clinica1 = Clinica(id_clinica=1, nombre="Clinica San Juan", nit="11111", estado="ACTIVO")
            clinica2 = Clinica(id_clinica=2, nombre="Clinica Los Andes", nit="22222", estado="ACTIVO")
            clinica_inactiva = Clinica(id_clinica=3, nombre="Clinica Inactiva", nit="33333", estado="INACTIVO")
            db.add_all([clinica1, clinica2, clinica_inactiva])
            db.commit()

            # 2. Roles & Permissions
            p1 = Permiso(id_permiso=1, nombre="users.read", modulo="users", accion="read", estado="ACTIVO")
            p2 = Permiso(id_permiso=2, nombre="users.write", modulo="users", accion="write", estado="ACTIVO")
            db.add_all([p1, p2])
            db.commit()

            rol_admin = Rol(id_rol=1, id_clinica=None, nombre="Administrador", estado="ACTIVO")
            rol_medico = Rol(id_rol=2, id_clinica=1, nombre="Médico", estado="ACTIVO")
            db.add_all([rol_admin, rol_medico])
            db.commit()

            rp1 = RolPermiso(id_rol=1, id_permiso=1)
            rp2 = RolPermiso(id_rol=1, id_permiso=2)
            db.add_all([rp1, rp2])
            db.commit()

            # 3. Usuarios
            # Super Admin (id_clinica is None, id_rol=1)
            super_admin = Usuario(
                id_usuario=1,
                id_clinica=None,
                id_rol=1,
                nombres="Super",
                apellidos="Admin",
                correo="superadmin@plataforma.com",
                password_hash=hash_password("Pass123!"),
                estado="ACTIVO",
                token_version=0,
            )
            # Tenant 1 Admin
            admin_tenant1 = Usuario(
                id_usuario=2,
                id_clinica=1,
                id_rol=1,
                nombres="Admin",
                apellidos="Tenant Uno",
                correo="admin@clinica1.com",
                password_hash=hash_password("Pass123!"),
                estado="ACTIVO",
                token_version=0,
            )
            # Tenant 1 User
            user_tenant1 = Usuario(
                id_usuario=3,
                id_clinica=1,
                id_rol=2,
                nombres="Doctor",
                apellidos="Uno",
                correo="doctor@clinica1.com",
                password_hash=hash_password("Pass123!"),
                estado="ACTIVO",
                token_version=0,
            )
            # Tenant 2 Admin
            admin_tenant2 = Usuario(
                id_usuario=4,
                id_clinica=2,
                id_rol=1,
                nombres="Admin",
                apellidos="Tenant Dos",
                correo="admin@clinica2.com",
                password_hash=hash_password("Pass123!"),
                estado="ACTIVO",
                token_version=0,
            )
            # Inactive Clinic User
            user_inactive_clinic = Usuario(
                id_usuario=5,
                id_clinica=3,
                id_rol=1,
                nombres="Admin",
                apellidos="Inactivo",
                correo="admin@clinicainactiva.com",
                password_hash=hash_password("Pass123!"),
                estado="ACTIVO",
                token_version=0,
            )
            db.add_all([super_admin, admin_tenant1, user_tenant1, admin_tenant2, user_inactive_clinic])
            db.commit()
        finally:
            db.close()

    def _auth_as(self, user_id: int):
        db = self.SessionLocal()
        user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
        db.close()
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    # =========================================================================
    # Test 1: Tenant Context (GET /api/v1/tenant/context)
    # =========================================================================
    def test_tenant_context_regular_user(self):
        self._auth_as(2)  # Tenant 1 Admin
        resp = self.client.get("/api/v1/tenant/context")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["clinica_id"], 1)
        self.assertEqual(data["clinica_nombre"], "Clinica San Juan")
        self.assertEqual(data["clinica_estado"], "ACTIVO")
        self.assertFalse(data["es_super_admin"])
        self.assertEqual(data["usuario_correo"], "admin@clinica1.com")
        self.assertIn("users.read", data["permisos"])

    def test_tenant_context_super_admin_without_header(self):
        self._auth_as(1)  # Super Admin
        resp = self.client.get("/api/v1/tenant/context")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNone(data["clinica_id"])
        self.assertEqual(data["clinica_nombre"], "")
        self.assertTrue(data["es_super_admin"])

    def test_tenant_context_super_admin_with_header(self):
        self._auth_as(1)  # Super Admin
        resp = self.client.get("/api/v1/tenant/context", headers={"X-Tenant-ID": "2"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["clinica_id"], 2)
        self.assertEqual(data["clinica_nombre"], "Clinica Los Andes")
        self.assertTrue(data["es_super_admin"])

    def test_tenant_context_inactive_clinic_returns_403(self):
        self._auth_as(5)  # User in inactive clinic
        resp = self.client.get("/api/v1/tenant/context")
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # Test 2: Super Admin Clinics Endpoints (GET/PATCH /api/v1/clinicas)
    # =========================================================================
    def test_list_clinicas_super_admin_success(self):
        self._auth_as(1)  # Super Admin
        resp = self.client.get("/api/v1/clinicas")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["total"], 3)
        self.assertIsInstance(data["items"], list)

    def test_list_clinicas_regular_user_forbidden(self):
        self._auth_as(2)  # Tenant Admin (not Super Admin)
        resp = self.client.get("/api/v1/clinicas")
        self.assertEqual(resp.status_code, 403)

    def test_patch_clinica_estado_super_admin(self):
        self._auth_as(1)  # Super Admin
        resp = self.client.patch("/api/v1/clinicas/2/estado", json={"estado": "INACTIVO"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["estado"], "INACTIVO")

        # Now tenant 2 user should be blocked
        self._auth_as(4)
        resp_t2 = self.client.get("/api/v1/tenant/context")
        self.assertEqual(resp_t2.status_code, 403)

    # =========================================================================
    # Test 3: Public Onboarding (POST /api/v1/public/clinicas/registrar)
    # =========================================================================
    def test_public_registration_success(self):
        payload = {
            "nombre": "Nueva Clinica San Pedro",
            "nit": "99999",
            "admin_nombres": "Pedro",
            "admin_apellidos": "Navarro",
            "admin_email": "pedro@sanpedro.com",
            "admin_password": "Password123!",
        }
        resp = self.client.post("/api/v1/public/clinicas/registrar", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("clinica", data)
        self.assertEqual(data["clinica"]["nombre"], "Nueva Clinica San Pedro")
        self.assertEqual(data["administrador"]["correo"], "pedro@sanpedro.com")

    def test_public_registration_duplicate_email(self):
        payload = {
            "nombre": "Otra Clinica",
            "admin_nombres": "Admin",
            "admin_apellidos": "Existente",
            "admin_email": "admin@clinica1.com",  # Already in DB
            "admin_password": "Password123!",
        }
        resp = self.client.post("/api/v1/public/clinicas/registrar", json=payload)
        self.assertEqual(resp.status_code, 400)

    # =========================================================================
    # Test 4: Tenant Data Isolation & Protection against Body Tenant Injection
    # =========================================================================
    def test_users_list_isolated_to_tenant(self):
        self._auth_as(2)  # Tenant 1 Admin
        resp = self.client.get("/api/v1/users")
        self.assertEqual(resp.status_code, 200)
        users = resp.json()
        # Tenant 1 has users 2 and 3
        tenant_ids = {u["id_clinica"] for u in users}
        self.assertEqual(tenant_ids, {1})
        emails = {u["correo"] for u in users}
        self.assertIn("admin@clinica1.com", emails)
        self.assertIn("doctor@clinica1.com", emails)
        self.assertNotIn("admin@clinica2.com", emails)

    def test_user_creation_with_foreign_tenant_id_in_body_rejected(self):
        self._auth_as(2)  # Tenant 1 Admin
        # Tries to inject id_clinica=2 in body
        payload = {
            "nombres": "Hacker",
            "apellidos": "User",
            "correo": "hacker@test.com",
            "password": "Password123!",
            "id_rol": 2,
            "id_clinica": 2,  # Different tenant!
        }
        resp = self.client.post("/api/v1/users", json=payload)
        self.assertEqual(resp.status_code, 400)

    def test_cross_tenant_user_detail_returns_404(self):
        self._auth_as(2)  # Tenant 1 Admin
        # Try to access User 4 (who belongs to Tenant 2)
        resp = self.client.get("/api/v1/users/4")
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # Test 5: TenantAwareService Base Class Test
    # =========================================================================
    def test_tenant_aware_service(self):
        db = self.SessionLocal()
        try:
            clinica1 = db.query(Clinica).filter(Clinica.id_clinica == 1).first()
            service = TenantAwareService(db, clinica1)

            # Test filter_by_tenant
            query = db.query(Usuario)
            filtered = service.filter_by_tenant(query, Usuario)
            users = filtered.all()
            for u in users:
                self.assertEqual(u.id_clinica, 1)

            # Test validate_ownership
            u_t1 = db.query(Usuario).filter(Usuario.id_usuario == 2).first()
            u_t2 = db.query(Usuario).filter(Usuario.id_usuario == 4).first()
            self.assertTrue(service.validate_ownership(u_t1))
            self.assertFalse(service.validate_ownership(u_t2))

            # Test get_or_404
            found = service.get_or_404(Usuario, "id_usuario", 2)
            self.assertEqual(found.id_usuario, 2)

            with self.assertRaises(Exception):
                # Cross tenant -> 404
                service.get_or_404(Usuario, "id_usuario", 4)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
