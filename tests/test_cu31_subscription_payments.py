import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Plan, Rol, Usuario, VersionPlan
from app.modules.tenants.models import SubscriptionPayment, TenantSubscription


class CU31SubscriptionPaymentsTestCase(unittest.TestCase):
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
            conn.exec_driver_sql("DELETE FROM subscription_payments")
            conn.exec_driver_sql("DELETE FROM tenant_subscriptions")
            conn.exec_driver_sql("DELETE FROM versiones_plan")
            conn.exec_driver_sql("DELETE FROM planes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

            # ClÃ­nicas: ClÃ­nica 1 y ClÃ­nica 2
            conn.exec_driver_sql("""
                INSERT INTO clinicas (id_clinica, tenant_id, nombre, nit, estado, row_version)
                VALUES (1, 'tenant-1-uuid', 'ClÃ­nica Los Olivos', '987654021', 'ACTIVE', 1),
                       (2, 'tenant-2-uuid', 'ClÃ­nica San Gabriel', '123456022', 'ACTIVE', 1)
            """)

            # Roles ADMIN para cada clÃ­nica
            conn.exec_driver_sql("""
                INSERT INTO roles (id_rol, id_clinica, nombre, estado)
                VALUES (1, 1, 'ADMIN', 'activo'),
                       (2, 2, 'ADMIN', 'activo')
            """)

            # Usuarios ADMIN
            conn.exec_driver_sql("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, token_version, notificaciones_push, notificaciones_email, notificaciones_sms)
                VALUES (1, 1, 1, 'Admin', 'Olivos', 'admin@olivos.com', 'hash', 'ACTIVO', 0, 1, 1, 0),
                       (2, 2, 2, 'Admin', 'Gabriel', 'admin@gabriel.com', 'hash', 'ACTIVO', 0, 1, 1, 0)
            """)

            # Planes canÃ³nicos CU34
            conn.exec_driver_sql("""
                INSERT INTO planes (id, codigo, activo, version_actual)
                VALUES (1, 'BASIC', 1, 1), (2, 'PRO', 1, 1)
            """)
            conn.exec_driver_sql("""
                INSERT INTO versiones_plan (
                    id, plan_id, numero, nombre, descripcion, precio_mensual,
                    moneda, ciclo, servicios_incluidos, limite_medicos,
                    limite_sedes, limite_consultas, tarifas_excedentes,
                    demora_pago_dias, creado_por
                )
                VALUES (101, 1, 1, 'Plan BÃ¡sico', 'Ideal para consultorios', 200.0,
                        'BOB', 'MENSUAL', '[]', 5, NULL, 50, '[]', 7, 1),
                       (102, 2, 1, 'Plan Profesional', 'Para clÃ­nicas medianas', 500.0,
                        'BOB', 'MENSUAL', '[]', 20, NULL, 300, '[]', 7, 1)
            """)

        self.db = self.SessionLocal()
        self.admin_tenant1 = self.db.get(Usuario, 1)
        self.admin_tenant2 = self.db.get(Usuario, 2)
        self.webhook_secret = "whsec_cu31_test"
        settings.STRIPE_WEBHOOK_SECRET = SecretStr(self.webhook_secret)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_current_user, None)

    def _post_webhook(
        self,
        id_pago=None,
        session_id=None,
        tipo="checkout.session.completed",
        url="/api/v1/payments/webhook/stripe/subscription",
    ):
        evento = {
            "id": "evt_cu31",
            "type": tipo,
            "data": {
                "object": {
                    "id": session_id or "cs_sub_test",
                    "metadata": {
                        "id_pago_suscripcion": id_pago or "",
                        "tipo": "suscripcion",
                    },
                }
            },
        }
        payload = json.dumps(evento).encode("utf-8")
        timestamp = int(time.time())
        firmado = f"{timestamp}.".encode("utf-8") + payload
        firma = hmac.new(
            self.webhook_secret.encode("utf-8"), firmado, hashlib.sha256
        ).hexdigest()
        return self.client.post(
            url,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": f"t={timestamp},v1={firma}",
            },
        )

    def test_tenant_sin_suscripcion_retorna_has_subscription_false(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        resp = self.client.get("/api/v1/subscriptions/current")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["has_subscription"])

    def test_listar_planes_activos(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        resp = self.client.get("/api/v1/subscriptions/plans")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        nombres = [p["nombre"] for p in data]
        self.assertIn("Plan BÃ¡sico", nombres)
        self.assertIn("Plan Profesional", nombres)

    def test_crear_checkout_calcula_monto_autoritativo_y_rechaza_campos_extra(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        # Intento de inyectar 'monto' o 'tenant_id' en el body debe responder 422
        resp_tamper = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={
                "plan_version_id": 102,
                "cycle": "ANNUAL",
                "monto": 10.0,
            },
        )
        self.assertEqual(resp_tamper.status_code, 422)

        # El ciclo anual queda explícitamente rechazado.
        resp_anual = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 102, "cycle": "ANNUAL"},
        )
        self.assertEqual(resp_anual.status_code, 422)

        # Checkout mensual para Plan Pro (debe calcular 500.0 BOB).
        resp_mensual = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 102, "cycle": "MONTHLY"},
        )
        self.assertEqual(resp_mensual.status_code, 201)
        data = resp_mensual.json()
        self.assertEqual(data["monto"], 500.0)
        self.assertEqual(data["moneda"], "BOB")
        self.assertTrue(data["checkout_url"])

    def test_checkout_usa_sesion_real_de_stripe_cuando_esta_configurado(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        with patch(
            "app.modules.tenants.subscription_payments.service.stripe_habilitado",
            return_value=True,
        ), patch(
            "app.modules.tenants.subscription_payments.service._crear_sesion_stripe",
            return_value={
                "id": "cs_test_real",
                "url": "https://checkout.stripe.com/c/pay/cs_test_real",
            },
        ) as crear_sesion:
            resp = self.client.post(
                "/api/v1/subscriptions/checkout",
                json={"plan_version_id": 102, "cycle": "MONTHLY"},
            )

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["checkout_url"].startswith("https://checkout.stripe.com/"))
        crear_sesion.assert_called_once()

    def test_webhook_sin_firma_valida_rechaza_y_no_confirma(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 101, "cycle": "MONTHLY"},
        )
        pago_id = resp_checkout.json()["id_pago"]

        evento = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_sub_test", "metadata": {"id_pago_suscripcion": pago_id}}},
        }
        resp = self.client.post(
            "/api/v1/payments/webhook/stripe/subscription",
            content=json.dumps(evento).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": "t=1,v1=firma-invalida",
            },
        )
        self.assertEqual(resp.status_code, 400)

        historial = self.client.get("/api/v1/subscription-payments").json()
        self.assertEqual(historial["items"][0]["estado"], "PENDING")

    def test_confirmacion_idempotente_y_extension_de_vigencia(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        # Crear checkout mensual para Plan BÃ¡sico (200.0 BOB)
        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 101, "cycle": "MONTHLY"},
        )
        pago_id = resp_checkout.json()["id_pago"]

        # Confirmar el pago vÃ­a webhook
        resp_webhook = self._post_webhook(id_pago=pago_id)
        self.assertEqual(resp_webhook.status_code, 200)
        self.assertEqual(resp_webhook.json()["estado"], "PAGADO")

        # Consultar suscripciÃ³n activa
        sub_resp = self.client.get("/api/v1/subscriptions/current")
        self.assertEqual(sub_resp.status_code, 200)
        sub_data = sub_resp.json()
        self.assertTrue(sub_data["has_subscription"])
        self.assertEqual(sub_data["estado"], "ACTIVE")
        self.assertEqual(sub_data["derived_status"], "ACTIVE")
        fin_primero = sub_data["fecha_fin"]

        # Reintento idÃ©ntico del webhook debe ser idempotente
        resp_webhook2 = self._post_webhook(id_pago=pago_id)
        self.assertEqual(resp_webhook2.status_code, 200)

        # La fecha fin no debe haber cambiado
        sub_resp2 = self.client.get("/api/v1/subscriptions/current")
        self.assertEqual(sub_resp2.json()["fecha_fin"], fin_primero)

    def test_webhook_raiz_despacha_suscripcion_por_metadatos(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1
        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 101, "cycle": "MONTHLY"},
        )
        pago_id = resp_checkout.json()["id_pago"]

        resp_webhook = self._post_webhook(id_pago=pago_id, url="/")
        self.assertEqual(resp_webhook.status_code, 200)
        self.assertEqual(resp_webhook.json()["estado"], "PAGADO")

        db = self.SessionLocal()
        pago = db.query(SubscriptionPayment).filter_by(
            id_pago_suscripcion=pago_id
        ).one()
        self.assertEqual(pago.estado, "PAGADO")
        db.close()

    def test_renovacion_mensual_inicia_el_dia_siguiente_al_vencimiento(self):
        db = self.SessionLocal()
        ahora = datetime.now(timezone.utc)
        fin_vigente = ahora + timedelta(days=10)
        db.add(
            TenantSubscription(
                id_clinica=1,
                id_version_plan=101,
                ciclo="MONTHLY",
                fecha_inicio=ahora - timedelta(days=20),
                fecha_fin=fin_vigente,
                estado="ACTIVE",
                row_version=1,
            )
        )
        db.commit()
        db.close()

        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1
        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 102, "cycle": "MONTHLY"},
        )
        pago_id = resp_checkout.json()["id_pago"]
        self.assertEqual(self._post_webhook(id_pago=pago_id).status_code, 200)

        db = self.SessionLocal()
        sub = db.query(TenantSubscription).filter_by(id_clinica=1).first()
        inicio = sub.fecha_inicio
        fin = sub.fecha_fin
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=timezone.utc)
        if fin.tzinfo is None:
            fin = fin.replace(tzinfo=timezone.utc)
        esperado_inicio = fin_vigente + timedelta(days=1)
        self.assertEqual(inicio.date(), esperado_inicio.date())
        self.assertEqual(fin.date(), (esperado_inicio + timedelta(days=29)).date())
        db.close()

    def test_descargar_comprobante_pdf_y_aislamiento_entre_tenants(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        # Crear y pagar suscripciÃ³n
        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 101, "cycle": "MONTHLY"},
        )
        pago_id = resp_checkout.json()["id_pago"]

        # Intento de descargar recibo antes de pagar responde 422
        resp_pdf_unpaid = self.client.get(f"/api/v1/subscription-payments/{pago_id}/receipt/pdf")
        self.assertEqual(resp_pdf_unpaid.status_code, 422)

        # Confirmar pago con webhook firmado
        self.assertEqual(self._post_webhook(id_pago=pago_id).status_code, 200)

        # Descargar comprobante en PDF como Tenant 1
        resp_pdf = self.client.get(f"/api/v1/subscription-payments/{pago_id}/receipt/pdf")
        self.assertEqual(resp_pdf.status_code, 200)
        self.assertEqual(resp_pdf.headers["content-type"], "application/pdf")
        self.assertTrue(resp_pdf.content.startswith(b"%PDF"))

        # Tenant 2 intentando acceder al comprobante de Tenant 1 debe recibir 404
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant2
        resp_pdf_alien = self.client.get(f"/api/v1/subscription-payments/{pago_id}/receipt/pdf")
        self.assertEqual(resp_pdf_alien.status_code, 404)


if __name__ == "__main__":
    unittest.main()
