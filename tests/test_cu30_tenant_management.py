import unittest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Auditoria, Clinica, Plan, Rol, Usuario, VersionPlan
from app.modules.appointments.models import Cita, Especialidad, Medico
from app.modules.medical_records.models import Paciente
from app.modules.tenants.models import PlanVersion, TenantRequest


class CU30TenantManagementTestCase(unittest.TestCase):
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
            conn.exec_driver_sql("DELETE FROM citas")
            conn.exec_driver_sql("DELETE FROM medicos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM auditoria")
            conn.exec_driver_sql("DELETE FROM tenant_requests")
            conn.exec_driver_sql("DELETE FROM tenant_subscriptions")
            conn.exec_driver_sql("DELETE FROM versiones_plan")
            conn.exec_driver_sql("DELETE FROM planes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

            # Clínica existente
            conn.exec_driver_sql("""
                INSERT INTO clinicas (id_clinica, tenant_id, nombre, razon_social, nit, correo, estado, row_version)
                VALUES (1, 'tenant-uuid-1', 'Clínica San Pedro', 'San Pedro S.A.', '111111028', 'info@sanpedro.com', 'ACTIVE', 1)
            """)

            # Roles:
            # 1: Global Super Administrador (id_clinica = NULL)
            # 2: Tenant ADMIN (id_clinica = 1)
            # 3: Tenant MEDICO (id_clinica = 1)
            # 4: Tenant PACIENTE (id_clinica = 1)
            conn.exec_driver_sql("""
                INSERT INTO roles (id_rol, id_clinica, nombre, estado)
                VALUES (1, NULL, 'Super Administrador', 'activo'),
                       (2, 1, 'ADMIN', 'activo'),
                       (3, 1, 'MEDICO', 'activo'),
                       (4, 1, 'PACIENTE', 'activo')
            """)

            # Usuarios:
            # 1: Super Admin global (id_clinica = NULL, id_rol = 1)
            # 2: Tenant Admin (id_clinica = 1, id_rol = 2)
            # 3: Doctor (id_clinica = 1, id_rol = 3)
            # 4: Paciente (id_clinica = 1, id_rol = 4)
            conn.exec_driver_sql("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, token_version, notificaciones_push, notificaciones_email, notificaciones_sms)
                VALUES (1, NULL, 1, 'Super', 'Admin', 'superadmin@global.com', 'hash', 'ACTIVO', 0, 1, 1, 0),
                       (2, 1, 2, 'Admin', 'Tenant', 'admin@tenant.com', 'hash', 'ACTIVO', 0, 1, 1, 0),
                       (3, 1, 3, 'Dr. Juan', 'Pérez', 'dr.perez@tenant.com', 'hash', 'ACTIVO', 0, 1, 1, 0),
                       (4, 1, 4, 'Carlos', 'Gómez', 'paciente@tenant.com', 'hash', 'ACTIVO', 0, 1, 1, 0)
            """)

            # Paciente y Médico
            conn.exec_driver_sql("""
                INSERT INTO pacientes (id_paciente, id_usuario, id_clinica, nombres, apellidos, ci, fecha_nacimiento, genero, telefono, estado)
                VALUES (1, 4, 1, 'Carlos', 'Gómez', '998877', '1990-05-10', 'M', '70000000', 'ACTIVO')
            """)
            conn.exec_driver_sql("""
                INSERT INTO medicos (id_medico, id_usuario, id_clinica, matricula_profesional, estado)
                VALUES (1, 3, 1, 'MAT-MED-01', 'activo')
            """)

            # Plan canónico CU34
            conn.exec_driver_sql("""
                INSERT INTO planes (id, codigo, activo, version_actual)
                VALUES (1, 'PRO_SALUD', 1, 1)
            """)
            conn.exec_driver_sql("""
                INSERT INTO versiones_plan (
                    id, plan_id, numero, nombre, precio_mensual, moneda, ciclo,
                    servicios_incluidos, limite_medicos, limite_sedes,
                    limite_consultas, tarifas_excedentes, demora_pago_dias, creado_por
                )
                VALUES (201, 1, 1, 'Plan Pro Salud', 500.0, 'BOB', 'MENSUAL',
                        '[]', 10, NULL, 100, '[]', 7, 1)
            """)

            # Tenant Request PENDING
            conn.exec_driver_sql("""
                INSERT INTO tenant_requests (id_request, institucion_nombre, razon_social, nit, correo, telefono, responsable_nombre, responsable_correo, id_version_plan, tracking_code, status, row_version)
                VALUES ('req-uuid-1', 'Clínica Santa Cruz', 'Santa Cruz S.R.L.', '554433221', 'contacto@santacruz.com', '71234567', 'Dra. María Lopez', 'maria@santacruz.com', 201, 'TRACK-123456', 'PENDING', 1)
            """)

        self.db = self.SessionLocal()
        self.super_admin_user = self.db.get(Usuario, 1)
        self.tenant_admin_user = self.db.get(Usuario, 2)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_current_user, None)

    def test_tenant_admin_rechazado_con_403(self):
        app.dependency_overrides[get_current_user] = lambda: self.tenant_admin_user

        resp = self.client.get("/api/v1/tenant-requests")
        self.assertEqual(resp.status_code, 403)

        resp2 = self.client.get("/api/v1/tenants")
        self.assertEqual(resp2.status_code, 403)

    def test_super_admin_lista_solicitudes_y_tenants(self):
        app.dependency_overrides[get_current_user] = lambda: self.super_admin_user

        resp = self.client.get("/api/v1/tenant-requests")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["institucion_nombre"], "Clínica Santa Cruz")

        resp_tenants = self.client.get("/api/v1/tenants")
        self.assertEqual(resp_tenants.status_code, 200)
        self.assertEqual(resp_tenants.json()["total"], 1)

    def test_aprobar_solicitud_crea_tenant_admin_y_auditoria(self):
        app.dependency_overrides[get_current_user] = lambda: self.super_admin_user

        resp = self.client.post(
            "/api/v1/tenant-requests/req-uuid-1/approve",
            json={"row_version": 1},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "APPROVED")
        self.assertIsNotNone(data["tenant_id"])

        # Segunda aprobación retorna 409
        resp_segunda = self.client.post(
            "/api/v1/tenant-requests/req-uuid-1/approve",
            json={"row_version": data["row_version"]},
        )
        self.assertEqual(resp_segunda.status_code, 409)

        # Se verificó creación de la clínica y el usuario admin
        nueva_clinica = self.db.query(Clinica).filter(Clinica.nit == "554433221").first()
        self.assertIsNotNone(nueva_clinica)
        self.assertEqual(nueva_clinica.estado, "ACTIVE")

        nuevo_admin = self.db.query(Usuario).filter(Usuario.correo == "maria@santacruz.com").first()
        self.assertIsNotNone(nuevo_admin)
        self.assertEqual(nuevo_admin.id_clinica, nueva_clinica.id_clinica)

        # Se auditó la acción
        aud = self.db.query(Auditoria).filter(Auditoria.accion == "APROBAR_TENANT_REQUEST").first()
        self.assertIsNotNone(aud)

    def test_rechazar_solicitud_marca_rejected_y_audita(self):
        app.dependency_overrides[get_current_user] = lambda: self.super_admin_user

        resp = self.client.post(
            "/api/v1/tenant-requests/req-uuid-1/reject",
            json={"reason": "Documentación tributaria vencida", "row_version": 1},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "REJECTED")
        self.assertEqual(data["decision_motivo"], "Documentación tributaria vencida")

        # No se creó clínica
        clinica = self.db.query(Clinica).filter(Clinica.nit == "554433221").first()
        self.assertIsNone(clinica)

    def test_suspender_tenant_y_verificar_bloqueo_de_nuevas_citas(self):
        app.dependency_overrides[get_current_user] = lambda: self.super_admin_user

        # Suspender Clínica 1
        resp = self.client.post(
            "/api/v1/tenants/1/suspend",
            json={"reason": "Mora en el pago de suscripción", "row_version": 1},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["estado"], "SUSPENDED")

        # Intentar crear nueva cita para este tenant debe responder 403
        app.dependency_overrides[get_current_user] = lambda: self.tenant_admin_user
        resp_cita = self.client.post(
            "/citas",
            json={
                "id_paciente": 1,
                "id_medico": 1,
                "fecha_cita": "2026-05-15",
                "hora_inicio": "10:00",
                "hora_fin": "10:30",
                "motivo": "Consulta general",
            },
        )
        self.assertEqual(resp_cita.status_code, 403)
        self.assertIn("suspendido", resp_cita.json()["detail"].lower())

    def test_version_obsoleta_responde_409(self):
        app.dependency_overrides[get_current_user] = lambda: self.super_admin_user

        resp = self.client.post(
            "/api/v1/tenants/1/suspend",
            json={"reason": "Mora", "row_version": 999},  # versión stale
        )
        self.assertEqual(resp.status_code, 409)

    def test_actualizar_acuerdo_comercial(self):
        app.dependency_overrides[get_current_user] = lambda: self.super_admin_user

        resp = self.client.put(
            "/api/v1/tenants/1/commercial-agreement",
            json={
                "plan_id": 201,
                "commercial_notes": "Condiciones mensuales especiales",
                "row_version": 1,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id_version_plan"], 201)
        self.assertEqual(data["commercial_notes"], "Condiciones mensuales especiales")

    def test_tenant_context_endpoint_compat(self):
        # 1. Tenant admin context
        app.dependency_overrides[get_current_user] = lambda: self.tenant_admin_user
        resp = self.client.get("/api/v1/tenant/context")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["clinica_id"], 1)
        self.assertEqual(data["usuario_id"], 2)
        self.assertEqual(data["rol"], "ADMIN")
        self.assertFalse(data["es_super_admin"])

        # Also accessible without prefix
        resp_noprefix = self.client.get("/tenant/context")
        self.assertEqual(resp_noprefix.status_code, 200)
        self.assertEqual(resp_noprefix.json()["clinica_id"], 1)

        # 2. Super admin context with X-Tenant-ID
        app.dependency_overrides[get_current_user] = lambda: self.super_admin_user
        resp_sa = self.client.get("/api/v1/tenant/context", headers={"X-Tenant-ID": "1"})
        self.assertEqual(resp_sa.status_code, 200)
        data_sa = resp_sa.json()
        self.assertEqual(data_sa["clinica_id"], 1)
        self.assertTrue(data_sa["es_super_admin"])


if __name__ == "__main__":
    unittest.main()
