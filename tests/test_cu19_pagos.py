"""Pruebas de CU19 - Procesar Pagos de Servicios Médicos.

Cubren el flujo completo en modo demostración (sin credenciales Stripe):
checkout, confirmación, comprobante PDF, QR y control de acceso; además de
la verificación de firma del webhook de Stripe.
"""
import hashlib
import hmac
import json
import time
import unittest
from datetime import date, time as dt_time
from unittest.mock import patch

from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.appointments.models import (
    Cita,
    Especialidad,
    Medico,
    MedicoEspecialidad,
    ServicioMedico,
)
from app.modules.medical_records.models import Paciente
from app.modules.payments import service as payments_service
from app.modules.payments.models import Pago


class CU19PagosTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)

        # Solo las tablas necesarias: otros módulos usan JSONB, no soportado por
        # el dialecto SQLite que se emplea en las pruebas unitarias.
        tablas = [
            Base.metadata.tables[nombre]
            for nombre in (
                "clinicas",
                "roles",
                "usuarios",
                "especialidades",
                "medicos",
                "medico_especialidad",
                "servicios_medicos",
                "pacientes",
                "citas",
                "pagos",
                "comprobantes",
            )
        ]
        Base.metadata.create_all(cls.engine, tables=tablas)

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
        self._reset_data()
        self._seed_data()
        self._mock_user(self.user_paciente)

        # Garantiza el modo demostración y evita escribir archivos reales.
        self._secret_patch = patch.object(
            settings, "STRIPE_SECRET_KEY", SecretStr("")
        )
        self._secret_patch.start()
        self._store_patch = patch.object(
            payments_service.storage, "store", return_value=("test/comprobante.pdf", "sha")
        )
        self._store_patch.start()
        self._read_patch = patch.object(
            payments_service.storage, "read", return_value=None
        )
        self._read_patch.start()

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)
        self._read_patch.stop()
        self._store_patch.stop()
        self._secret_patch.stop()

    def _mock_user(self, user: Usuario):
        user_id = sa_inspect(user).identity[0]

        def current_user(db: Session = Depends(get_db)):
            return db.query(Usuario).filter(Usuario.id_usuario == user_id).first()

        app.dependency_overrides[get_current_user] = current_user

    def _reset_data(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM comprobantes")
            conn.exec_driver_sql("DELETE FROM pagos")
            conn.exec_driver_sql("DELETE FROM citas")
            conn.exec_driver_sql("DELETE FROM servicios_medicos")
            conn.exec_driver_sql("DELETE FROM medico_especialidad")
            conn.exec_driver_sql("DELETE FROM especialidades")
            conn.exec_driver_sql("DELETE FROM medicos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

    def _seed_data(self):
        db = self.SessionLocal()
        try:
            db.add(Clinica(id_clinica=1, nombre="Clínica San Juan"))

            db.add_all(
                [
                    Rol(id_rol=1, id_clinica=1, nombre="Administrador", estado="ACTIVO"),
                    Rol(id_rol=2, id_clinica=1, nombre="Médico", estado="ACTIVO"),
                    Rol(id_rol=4, id_clinica=1, nombre="Paciente", estado="ACTIVO"),
                ]
            )

            self.user_admin = Usuario(
                id_usuario=1, id_clinica=1, id_rol=1,
                nombres="Admin", apellidos="Hospital", correo="admin@hospital.com",
                password_hash="hash", estado="ACTIVO",
            )
            user_medico = Usuario(
                id_usuario=2, id_clinica=1, id_rol=2,
                nombres="Carlos", apellidos="Mendoza", correo="carlos@hospital.com",
                password_hash="hash", estado="ACTIVO",
            )
            self.user_paciente = Usuario(
                id_usuario=3, id_clinica=1, id_rol=4,
                nombres="Ana", apellidos="Gomez", correo="ana@test.com",
                password_hash="hash", estado="ACTIVO",
            )
            self.user_otro = Usuario(
                id_usuario=4, id_clinica=1, id_rol=4,
                nombres="Luis", apellidos="Perez", correo="luis@test.com",
                password_hash="hash", estado="ACTIVO",
            )
            db.add_all([self.user_admin, user_medico, self.user_paciente, self.user_otro])
            db.flush()

            db.add(Especialidad(id_especialidad=1, nombre="Cardiología", estado="activo"))
            db.add(
                Medico(
                    id_medico=1, id_usuario=2, matricula_profesional="MED-1234",
                    estado="activo",
                )
            )
            db.add(
                MedicoEspecialidad(id_medico=1, id_especialidad=1, es_principal=True)
            )
            db.add(
                ServicioMedico(
                    id_servicio=1, nombre="Consulta cardiológica",
                    hora_inicio=dt_time(8, 0), hora_fin=dt_time(18, 0),
                    duracion_minutos=30, costo=120.50, estado="activo",
                )
            )
            db.add_all(
                [
                    Paciente(
                        id_paciente=1, id_clinica=1, id_usuario=3,
                        nombres="Ana", apellidos="Gomez", ci="8877665",
                        complemento="1A", fecha_nacimiento=date(1990, 1, 1),
                        genero="F", telefono="70011223", estado="ACTIVO",
                    ),
                    Paciente(
                        id_paciente=2, id_clinica=1, id_usuario=4,
                        nombres="Luis", apellidos="Perez", ci="1122334",
                        complemento="", fecha_nacimiento=date(1985, 5, 5),
                        genero="M", telefono="70099887", estado="ACTIVO",
                    ),
                ]
            )
            db.flush()

            db.add_all(
                [
                    Cita(
                        id_cita=1, id_clinica=1, id_paciente=1, id_medico=1,
                        id_especialidad=1, id_servicio=1, fecha_cita=date(2026, 11, 10),
                        hora_inicio="09:00", hora_fin="09:30", motivo="Control",
                        estado="PENDIENTE", tipo_consulta="TELEMEDICINA",
                    ),
                    Cita(
                        id_cita=2, id_clinica=1, id_paciente=2, id_medico=1,
                        id_especialidad=1, id_servicio=1, fecha_cita=date(2026, 11, 11),
                        hora_inicio="10:00", hora_fin="10:30", motivo="Chequeo",
                        estado="PENDIENTE", tipo_consulta="PRESENCIAL",
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Pruebas
    # ------------------------------------------------------------------ #
    def test_flujo_checkout_comprobante_y_qr(self):
        resp = self.client.get("/pagos/pendientes")
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(str(data["items"][0]["monto"]), "120.50")
        self.assertEqual(data["items"][0]["id_cita"], 1)

        resp = self.client.post(
            "/pagos/checkout", json={"id_cita": 1, "canal": "WEB", "metodo_pago": "TARJETA"}
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        checkout = resp.json()
        self.assertTrue(checkout["simulado"])
        self.assertEqual(checkout["estado"], "PENDIENTE")
        self.assertIsNotNone(checkout["url_checkout"])
        self.assertIsNotNone(checkout["qr_url"])
        self.assertIn("/pagos/qr/", checkout["qr_payload"])
        id_pago = checkout["id_pago"]

        # Confirmación en modo demostración
        resp = self.client.post(f"/pagos/{id_pago}/simular-pago")
        self.assertEqual(resp.status_code, 200, resp.text)
        pago = resp.json()
        self.assertEqual(pago["estado"], "PAGADO")
        self.assertIsNotNone(pago["comprobante"])
        self.assertTrue(pago["comprobante"]["numero_comprobante"].startswith("REC-"))

        # La cita queda confirmada
        with self.SessionLocal() as db:
            cita = db.query(Cita).filter(Cita.id_cita == 1).first()
            self.assertEqual(cita.estado, "CONFIRMADA")

        # Comprobante PDF
        resp = self.client.get(f"/pagos/{id_pago}/comprobante/pdf")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

        # QR PNG
        resp = self.client.get(f"/pagos/{id_pago}/qr")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers["content-type"], "image/png")
        self.assertTrue(resp.content.startswith(b"\x89PNG"))

        # Historial
        resp = self.client.get("/pagos/mis-pagos")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["total"], 1)

    def test_paciente_no_puede_pagar_cita_ajena(self):
        self._mock_user(self.user_otro)
        resp = self.client.post("/pagos/checkout", json={"id_cita": 1})
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_webhook_stripe_confirma_pago(self):
        resp = self.client.post("/pagos/checkout", json={"id_cita": 1})
        id_pago = resp.json()["id_pago"]

        evento = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_test_123",
                    "payment_status": "paid",
                    "status": "complete",
                    "metadata": {"id_pago": str(id_pago)},
                }
            },
        }
        body = json.dumps(evento).encode("utf-8")
        timestamp = int(time.time())
        firmado = f"{timestamp}.".encode("utf-8") + body
        firma = hmac.new(b"whsec_test", firmado, hashlib.sha256).hexdigest()

        with patch.object(settings, "STRIPE_WEBHOOK_SECRET", SecretStr("whsec_test")):
            resp = self.client.post(
                "/pagos/webhook/stripe",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Stripe-Signature": f"t={timestamp},v1={firma}",
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["estado"], "PAGADO")

        with self.SessionLocal() as db:
            pago = db.query(Pago).filter(Pago.id_pago == id_pago).first()
            self.assertEqual(pago.estado, "PAGADO")
            self.assertEqual(pago.referencia_transaccion, "pi_test_123")

    def test_simulado_deshabilitado_cuando_stripe_esta_configurado(self):
        resp = self.client.post("/pagos/checkout", json={"id_cita": 1})
        id_pago = resp.json()["id_pago"]

        with self.SessionLocal() as db:
            token = db.query(Pago).filter(Pago.id_pago == id_pago).first().qr_token

        with patch.object(settings, "STRIPE_SECRET_KEY", SecretStr("sk_test_123")):
            resp_simular = self.client.post(f"/pagos/{id_pago}/simular-pago")
            resp_token = self.client.post(f"/pagos/simulado/{token}/confirmar")

        self.assertEqual(resp_simular.status_code, 409, resp_simular.text)
        self.assertEqual(resp_token.status_code, 409, resp_token.text)

        with self.SessionLocal() as db:
            pago = db.query(Pago).filter(Pago.id_pago == id_pago).first()
            self.assertEqual(pago.estado, "PENDIENTE")

    def test_webhook_firma_invalida(self):
        with patch.object(settings, "STRIPE_WEBHOOK_SECRET", SecretStr("whsec_test")):
            resp = self.client.post(
                "/pagos/webhook/stripe",
                content=b'{"type":"checkout.session.completed"}',
                headers={"Stripe-Signature": "t=1,v1=invalida"},
            )
        self.assertEqual(resp.status_code, 400, resp.text)


if __name__ == "__main__":
    unittest.main()
