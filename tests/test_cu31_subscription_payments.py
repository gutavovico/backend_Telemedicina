import hashlib
import hmac
import json
import time
import unittest
from app.modules.tenants.billing import utc, next_month
from app.modules.auth.models import Plan, VersionPlan
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
from app.modules.auth.models import Clinica, Rol, Usuario
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
            conn.exec_driver_sql("DELETE FROM subscription_changes")
            conn.exec_driver_sql("DELETE FROM subscription_payments")
            conn.exec_driver_sql("DELETE FROM tenant_subscriptions")
            conn.exec_driver_sql("DELETE FROM plan_versions")
            conn.exec_driver_sql("DELETE FROM versiones_plan")
            conn.exec_driver_sql("DELETE FROM planes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

            # Clínicas: Clínica 1 y Clínica 2
            conn.exec_driver_sql("""
                INSERT INTO clinicas (id_clinica, tenant_id, nombre, nit, estado, row_version)
                VALUES (1, 'tenant-1-uuid', 'Clínica Los Olivos', '987654021', 'ACTIVE', 1),
                       (2, 'tenant-2-uuid', 'Clínica San Gabriel', '123456022', 'ACTIVE', 1)
            """)

            # Roles ADMIN para cada clínica
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

        with self.SessionLocal() as db:
            for vid, name, price, doctors, consultations in [(1,'Plan Básico','200.00',5,50),(2,'Plan Profesional','500.00',20,300)]:
                db.add(Plan(id=vid,codigo='TEST'+str(vid),activo=True,version_actual=1));db.flush()
                db.add(VersionPlan(id=vid,plan_id=vid,numero=1,nombre=name,precio_mensual=price,
                    moneda='BOB',ciclo='MENSUAL',servicios_incluidos=[],limite_medicos=doctors,
                    limite_consultas=consultations,limite_sedes=None,tarifas_excedentes=[],demora_pago_dias=0,creado_por=1))
            db.commit()

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
        with self.SessionLocal() as db:
            payment = db.get(SubscriptionPayment, id_pago)
            actual_session = payment.stripe_session_id if payment else session_id
            amount = int(payment.monto * 100) if payment else 0
        evento = {
            "id": "evt_cu31",
            "type": tipo,
            "data": {
                "object": {
                    "id": session_id or actual_session,
                    "payment_status":"paid", "currency":"bob", "amount_total":amount,
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
        self.assertIn("Plan Básico", nombres)
        self.assertIn("Plan Profesional", nombres)

    def test_crear_checkout_calcula_monto_autoritativo_y_rechaza_campos_extra(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        # Intento de inyectar 'monto' o 'tenant_id' en el body debe responder 422
        resp_tamper = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={
                "plan_version_id": 2,
                "cycle": "MENSUAL",
                "monto": 10.0,
            },
        )
        self.assertEqual(resp_tamper.status_code, 422)

        # Checkout mensual CU34: importe autoritativo 500.00 BOB
        resp_annual = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={
                "plan_version_id": 2,
                "cycle": "MENSUAL",
            },
        )
        self.assertEqual(resp_annual.status_code, 201)
        data = resp_annual.json()
        self.assertEqual(data["monto"], "500.00")
        self.assertEqual(data["moneda"], "BOB")
        # Sin credenciales la sesión es simulada, pero nunca confirma el pago.
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
                json={"plan_version_id": 2, "cycle": "MENSUAL"},
            )

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["checkout_url"].startswith("https://checkout.stripe.com/"))
        crear_sesion.assert_called_once()

    def test_webhook_sin_firma_valida_rechaza_y_no_confirma(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 1, "cycle": "MENSUAL"},
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

        # Crear checkout mensual para Plan Básico (200.0 BOB)
        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 1, "cycle": "MENSUAL"},
        )
        pago_id = resp_checkout.json()["id_pago"]

        # Confirmar el pago vía webhook
        resp_webhook = self._post_webhook(id_pago=pago_id)
        self.assertEqual(resp_webhook.status_code, 200)
        self.assertEqual(resp_webhook.json()["estado"], "PAGADO")

        # Consultar suscripción activa
        sub_resp = self.client.get("/api/v1/subscriptions/current")
        self.assertEqual(sub_resp.status_code, 200)
        sub_data = sub_resp.json()
        self.assertTrue(sub_data["has_subscription"])
        self.assertEqual(sub_data["estado"], "ACTIVE")
        self.assertEqual(sub_data["derived_status"], "ACTIVE")
        fin_primero = sub_data["fecha_fin"]

        # Reintento idéntico del webhook debe ser idempotente
        resp_webhook2 = self._post_webhook(id_pago=pago_id)
        self.assertEqual(resp_webhook2.status_code, 200)

        # La fecha fin no debe haber cambiado
        sub_resp2 = self.client.get("/api/v1/subscriptions/current")
        self.assertEqual(sub_resp2.json()["fecha_fin"], fin_primero)

    def test_webhook_raiz_despacha_suscripcion_por_metadatos(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1
        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 1, "cycle": "MONTHLY"},
        )
        self.assertEqual(resp_checkout.status_code, 201)
        pago_id = resp_checkout.json()["id_pago"]

        resp_webhook = self._post_webhook(id_pago=pago_id, url="/")
        self.assertEqual(resp_webhook.status_code, 200)
        self.assertEqual(resp_webhook.json()["estado"], "PAGADO")

        db = self.SessionLocal()
        pago = db.get(SubscriptionPayment, pago_id)
        self.assertEqual(pago.estado, "PAGADO")
        db.close()

    def test_renovacion_mensual_preserva_cierre_y_espera_fecha_efectiva(self):
        db = self.SessionLocal()
        ahora = datetime.now(timezone.utc)
        inicio = ahora - timedelta(days=20)
        fin_vigente = ahora + timedelta(days=10)
        sub=TenantSubscription(id_clinica=1,id_version_plan=1,ciclo='MENSUAL',fecha_inicio=inicio,
            fecha_fin=fin_vigente,estado='ACTIVE',billing_anchor_day=inicio.day,row_version=1)
        db.add(sub);db.commit();db.close()
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1
        resp=self.client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':1,'cycle':'MENSUAL'})
        self.assertEqual(resp.status_code,201)
        self.assertEqual(self._post_webhook(id_pago=resp.json()['id_pago']).status_code,200)
        with self.SessionLocal() as db:
            sub=db.query(TenantSubscription).filter_by(id_clinica=1).first()
            self.assertEqual(utc(sub.fecha_inicio),inicio)
            self.assertEqual(utc(sub.fecha_fin),fin_vigente)
            payment=db.get(SubscriptionPayment,resp.json()['id_pago'])
            self.assertEqual(utc(payment.period_start),fin_vigente)
            self.assertEqual(utc(payment.period_end),next_month(fin_vigente,inicio.day))

    def test_ciclo_anual_se_rechaza(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1
        response=self.client.post('/api/v1/subscriptions/checkout',json={'plan_version_id':1,'cycle':'ANNUAL'})
        self.assertEqual(response.status_code,422)

    def test_descargar_comprobante_pdf_y_aislamiento_entre_tenants(self):
        app.dependency_overrides[get_current_user] = lambda: self.admin_tenant1

        # Crear y pagar suscripción
        resp_checkout = self.client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_version_id": 1, "cycle": "MENSUAL"},
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
