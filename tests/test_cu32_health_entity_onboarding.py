import io
import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.tenants.models import PlanVersion, TenantDeactivationRequest, TenantRequest
from app.modules.tenants.public_onboarding.service import reset_public_rate_limits


class CU32HealthEntityOnboardingTestCase(unittest.TestCase):
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
            conn.exec_driver_sql("DELETE FROM tenant_deactivation_requests")
            conn.exec_driver_sql("DELETE FROM tenant_requests")
            conn.exec_driver_sql("DELETE FROM plan_versions")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

            # Clínica 1 (ACTIVO) y Clínica 2 (SUSPENDIDO)
            conn.exec_driver_sql("""
                INSERT INTO clinicas (id_clinica, tenant_id, nombre, nit, estado, row_version)
                VALUES (1, 'tenant-active-uuid', 'Hospital San Martin', '100200300', 'ACTIVO', 1),
                       (2, 'tenant-suspended-uuid', 'Clínica Pausada', '400500600', 'SUSPENDIDO', 1)
            """)

            # Roles ADMIN y rol global Super Administrador
            conn.exec_driver_sql("""
                INSERT INTO roles (id_rol, id_clinica, nombre, estado)
                VALUES (1, 1, 'ADMIN', 'activo'),
                       (2, 2, 'ADMIN', 'activo'),
                       (3, NULL, 'SUPER ADMINISTRADOR', 'activo')
            """)

            # Usuario ADMIN para Clínica 1
            conn.exec_driver_sql("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, token_version, notificaciones_push, notificaciones_email, notificaciones_sms)
                VALUES (10, 1, 1, 'Admin', 'San Martin', 'admin@sanmartin.org', 'fakehash', 'activo', 0, 1, 1, 0)
            """)

            # Usuario ADMIN para Clínica 2 (Suspendida)
            conn.exec_driver_sql("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, token_version, notificaciones_push, notificaciones_email, notificaciones_sms)
                VALUES (20, 2, 2, 'Admin', 'Pausada', 'admin@pausada.org', 'fakehash', 'activo', 0, 1, 1, 0)
            """)

            # Super Administrador global (sin clínica)
            conn.exec_driver_sql("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, token_version, notificaciones_push, notificaciones_email, notificaciones_sms)
                VALUES (1, NULL, 3, 'Super', 'Admin', 'super@global.org', 'fakehash', 'activo', 0, 1, 1, 0)
            """)

            # Plan activo
            conn.exec_driver_sql("""
                INSERT INTO plan_versions (id_plan_version, nombre, precio_mensual, precio_anual, moneda, limite_medicos, limite_consultas_mes, estado)
                VALUES ('plan-hosp-v1', 'Plan Hospitalario', 250.00, 2500.00, 'BOB', 50, 1000, 'ACTIVO')
            """)

    def test_public_onboarding_success_pending(self):
        """Envío exitoso de solicitud pública con documentos retorna 202 y estado PENDING."""
        file_content = b"%PDF-1.4 test document content"
        files = [
            ("documentos", ("licencia_salud.pdf", io.BytesIO(file_content), "application/pdf")),
        ]
        data = {
            "nombre": "Clínica Esperanza",
            "razon_social": "Esperanza Salud S.R.L.",
            "nit": "778899001",
            "correo": "contacto@clinicaesperanza.com",
            "telefono": "78912345",
            "direccion": "Av. Principal 456",
            "responsable_nombre": "Dr. Carlos Ramos",
            "responsable_correo": "cramos@clinicaesperanza.com",
            "responsable_telefono": "78912346",
            "plan_version_id": "plan-hosp-v1",
        }

        res = self.client.post("/api/v1/public/tenant-requests", data=data, files=files)
        self.assertEqual(res.status_code, 202)
        body = res.json()
        self.assertIn("id_request", body)
        self.assertIn("tracking_code", body)
        self.assertEqual(body["status"], "PENDING")

        # Verificar en base de datos: solicitud en PENDING y NO se creó clínica ni usuario activo
        db = self.SessionLocal()
        req = db.query(TenantRequest).filter_by(id_request=body["id_request"]).first()
        self.assertIsNotNone(req)
        self.assertEqual(req.status, "PENDING")
        self.assertEqual(req.responsable_nombre, "Dr. Carlos Ramos")
        self.assertIn("licencia_salud.pdf", req.documentos_metadata)

        # No debe haber clínica con dicho nombre ni tenant activo generado
        clinica = db.query(Clinica).filter_by(nombre="Clínica Esperanza").first()
        self.assertIsNone(clinica)
        db.close()

    def test_public_onboarding_duplicate_nit_conflict(self):
        """Si el NIT ya existe en una entidad activa o solicitud PENDING, devuelve 409 Conflict."""
        # NIT de Clinica 1 que ya existe: 100200300
        data = {
            "nombre": "Clínica Falsa",
            "nit": "100-200-300",  # Con formato, debe normalizarse y coincidir
            "correo": "falsa@test.com",
            "responsable_nombre": "Director Falso",
            "responsable_correo": "director@test.com",
        }
        res = self.client.post("/api/v1/public/tenant-requests", data=data)
        self.assertEqual(res.status_code, 409)
        self.assertIn("Ya existe una solicitud pendiente o entidad activa con este NIT", res.json()["detail"])

    def test_public_onboarding_disallowed_file_extension(self):
        """Archivos ejecutables o no permitidos devuelven 422."""
        files = [
            ("documentos", ("malware.exe", io.BytesIO(b"malicious content"), "application/octet-stream")),
        ]
        data = {
            "nombre": "Clínica Test",
            "nit": "999888777",
            "correo": "test@test.com",
            "responsable_nombre": "Dr. Test",
            "responsable_correo": "drtest@test.com",
        }
        res = self.client.post("/api/v1/public/tenant-requests", data=data, files=files)
        self.assertEqual(res.status_code, 422)
        self.assertIn("Extensión no permitida", res.json()["detail"])

    def test_tracking_endpoint(self):
        """Consulta con código válido devuelve estado mínimo y 404 para código erróneo."""
        # 1. Crear una solicitud primero
        data = {
            "nombre": "San Lucas Medical",
            "nit": "555666777",
            "correo": "info@sanlucas.com",
            "responsable_nombre": "Lic. Ana Gomez",
            "responsable_correo": "agomez@sanlucas.com",
        }
        res_create = self.client.post("/api/v1/public/tenant-requests", data=data)
        self.assertEqual(res_create.status_code, 202)
        code = res_create.json()["tracking_code"]

        # 2. Consultar con código válido
        res_track = self.client.get(f"/api/v1/public/tenant-requests/{code}")
        self.assertEqual(res_track.status_code, 200)
        track_body = res_track.json()
        self.assertEqual(track_body["institucion"], "San Lucas Medical")
        self.assertEqual(track_body["status"], "PENDING")
        self.assertIn("revisión", track_body["mensaje"])
        # No debe haber campos sensibles expuestos
        self.assertNotIn("documentos_metadata", track_body)
        self.assertNotIn("correo", track_body)

        # 3. Código no existente devuelve 404
        res_track_404 = self.client.get("/api/v1/public/tenant-requests/CODIGO-INEXISTENTE-123")
        self.assertEqual(res_track_404.status_code, 404)

    def test_deactivation_request_success(self):
        """Admin de clínica activa solicita baja formal exitosamente (202 PENDING, sin borrar datos)."""
        db = self.SessionLocal()
        admin_user = db.query(Usuario).filter_by(id_usuario=10).first()
        app.dependency_overrides[get_current_user] = lambda: admin_user

        payload = {"motivo": "Fusión institucional con otro centro de salud y cese de operaciones locales."}
        res = self.client.post("/api/v1/tenant/deactivation-requests", json=payload)
        self.assertEqual(res.status_code, 202)
        body = res.json()
        self.assertEqual(body["status"], "PENDING")
        self.assertIn("id_deactivation", body)

        # Verificar que la clínica y sus datos permanecen intactos
        clinica = db.query(Clinica).filter_by(id_clinica=1).first()
        self.assertIsNotNone(clinica)
        self.assertEqual(clinica.estado, "ACTIVO")

        # Verificar registro en tabla de solicitudes de baja
        deact = db.query(TenantDeactivationRequest).filter_by(id_deactivation=body["id_deactivation"]).first()
        self.assertIsNotNone(deact)
        self.assertEqual(deact.motivo, payload["motivo"])
        self.assertEqual(deact.solicitante_id, 10)
        db.close()

    def test_public_onboarding_rejects_mime_signature_mismatch(self):
        """Un ejecutable renombrado a PDF se rechaza por contenido real, no por extensión."""
        files = [
            ("documentos", ("licencia.pdf", io.BytesIO(b"MZ\\x90\\x00 ejecutable"), "application/pdf")),
        ]
        data = {
            "nombre": "Clínica Riesgo",
            "nit": "321321321",
            "correo": "riesgo@test.com",
            "responsable_nombre": "Dr. Riesgo",
            "responsable_correo": "riesgo@test.com",
        }
        res = self.client.post("/api/v1/public/tenant-requests", data=data, files=files)
        self.assertEqual(res.status_code, 422)
        self.assertIn("no coincide", res.json()["detail"])

    def test_public_onboarding_rate_limit_returns_429(self):
        """El portal público limita solicitudes repetidas por correo de contacto."""
        ultimo = None
        for i in range(6):
            data = {
                "nombre": f"Clínica Limite {i}",
                "nit": f"90000000{i}",
                "correo": "limite@test.com",
                "responsable_nombre": "Lic. Límite",
                "responsable_correo": "limite@test.com",
            }
            ultimo = self.client.post("/api/v1/public/tenant-requests", data=data)
        self.assertEqual(ultimo.status_code, 429)

    def test_deactivation_request_visible_y_aprobable_por_super_admin(self):
        """El Super Admin lista y aprueba la baja aplicando baja lógica sin borrar datos."""
        db = self.SessionLocal()
        admin_user = db.query(Usuario).filter_by(id_usuario=10).first()
        app.dependency_overrides[get_current_user] = lambda: admin_user
        res = self.client.post(
            "/api/v1/tenant/deactivation-requests",
            json={"motivo": "Cese de operaciones solicitado por la dirección institucional."},
        )
        self.assertEqual(res.status_code, 202)
        id_deact = res.json()["id_deactivation"]

        super_admin = db.query(Usuario).filter_by(id_usuario=1).first()
        app.dependency_overrides[get_current_user] = lambda: super_admin

        listado = self.client.get("/api/v1/tenant/deactivation-requests?status=PENDING")
        self.assertEqual(listado.status_code, 200)
        self.assertEqual(listado.json()["total"], 1)

        aprobacion = self.client.post(
            f"/api/v1/tenant/deactivation-requests/{id_deact}/approve",
            json={"row_version": 1},
        )
        self.assertEqual(aprobacion.status_code, 200)
        self.assertEqual(aprobacion.json()["status"], "APPROVED")

        clinica = db.query(Clinica).filter_by(id_clinica=1).first()
        self.assertEqual(clinica.estado, "INACTIVE")
        self.assertIsNotNone(db.query(Clinica).filter_by(id_clinica=1).first())
        db.close()

    def test_deactivation_request_conflict_when_suspended(self):
        """Admin de clínica SUSPENDIDA no puede solicitar baja (retorna 409)."""
        db = self.SessionLocal()
        suspended_admin = db.query(Usuario).filter_by(id_usuario=20).first()
        app.dependency_overrides[get_current_user] = lambda: suspended_admin

        payload = {"motivo": "Cierre definitivo"}
        res = self.client.post("/api/v1/tenant/deactivation-requests", json=payload)
        self.assertEqual(res.status_code, 409)
        self.assertIn("Solo una entidad de salud en estado ACTIVO", res.json()["detail"])
        db.close()


if __name__ == "__main__":
    unittest.main()
