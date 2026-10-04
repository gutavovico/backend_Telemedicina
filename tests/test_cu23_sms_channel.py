"""Pruebas del canal de recuperación por SMS (CU23).

Cubren los escenarios Gherkin del requisito "Despacho del Código de Recuperación
por SMS": envío con Twilio, modo consola, usuario sin teléfono y fallo del
proveedor sin filtrar información del usuario.

Twilio se prueba con un cliente simulado inyectado en el adaptador, porque el SDK
no es una dependencia del proyecto (import diferido, decision D5) y porque no
deben salir llamadas a un proveedor real desde la suite.
"""
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import sms as sms_module
from app.core.config import settings
from app.core.database import get_db
from app.core.sms import (
    ConsoleSmsProvider,
    TwilioSmsProvider,
    get_sms_provider,
    send_password_reset_sms,
)
from app.main import app
from app.modules.auth.models import Usuario

GENERICO = "Si el correo está registrado, recibirás un código de recuperación."


class SmsChannelTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        cls._create_schema()

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)

    @classmethod
    def _create_schema(cls):
        with cls.engine.begin() as conn:
            conn.exec_driver_sql("""
                CREATE TABLE usuarios (
                    id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NULL,
                    id_rol INTEGER NULL,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL,
                    correo TEXT NOT NULL UNIQUE,
                    telefono TEXT NULL,
                    password_hash TEXT NOT NULL,
                    foto_perfil TEXT NULL,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO',
                    notificaciones_push BOOLEAN NOT NULL DEFAULT 1,
                    notificaciones_email BOOLEAN NOT NULL DEFAULT 1,
                    notificaciones_sms BOOLEAN NOT NULL DEFAULT 0,
                    token_version INTEGER NOT NULL DEFAULT 0,
                    fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    fecha_actualizacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # `Usuario.rol_rel` usa lazy="joined": get_user_by_email trae un JOIN contra
            # roles, asi que la tabla debe existir.
            conn.exec_driver_sql("""
                CREATE TABLE roles (
                    id_rol INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NULL,
                    nombre TEXT NOT NULL,
                    descripcion TEXT NULL,
                    estado TEXT NOT NULL,
                    fecha_creacion TIMESTAMP NULL
                )
            """)
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, nombre, estado) VALUES (4, 'PACIENTE', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, "
                "correo, telefono, password_hash, estado, notificaciones_push, "
                "notificaciones_email, notificaciones_sms, token_version) VALUES "
                "(1, 7, 4, 'Luis', 'Gomez', 'con.telefono@ejemplo.com', '+59170000000', 'x', "
                "'ACTIVO', 1, 1, 0, 0),"
                "(2, 7, 4, 'Ana', 'Sin', 'sin.telefono@ejemplo.com', NULL, 'x', "
                "'ACTIVO', 1, 1, 0, 0)"
            )

    def setUp(self):
        self.client = TestClient(app)
        self._provider_previo = settings.SMS_PROVIDER

    def tearDown(self):
        settings.SMS_PROVIDER = self._provider_previo

    # ------------------------------------------------------------------ #
    # 4.1 Adaptador de consola
    # ------------------------------------------------------------------ #
    def test_proveedor_por_defecto_es_consola(self):
        settings.SMS_PROVIDER = "console"
        self.assertIsInstance(get_sms_provider(), ConsoleSmsProvider)

    def test_proveedor_configurado_es_twilio(self):
        settings.SMS_PROVIDER = "twilio"
        self.assertIsInstance(get_sms_provider(), TwilioSmsProvider)

    def test_consola_devuelve_el_codigo_y_no_sale_a_la_red(self):
        settings.SMS_PROVIDER = "console"
        proveedor = MagicMock()
        with patch.object(sms_module, "get_sms_provider", return_value=proveedor):
            codigo = send_password_reset_sms("+59170000000", "123456")

        self.assertEqual(codigo, "123456")
        proveedor.send.assert_called_once()
        cuerpo = proveedor.send.call_args[0][1]
        self.assertIn("123456", cuerpo)
        self.assertIn(str(settings.RESET_CODE_TTL_MINUTES), cuerpo)

    # ------------------------------------------------------------------ #
    # 4.2 Adaptador Twilio
    # ------------------------------------------------------------------ #
    def test_twilio_envia_al_telefono_correspondiente(self):
        cliente = MagicMock()
        proveedor = TwilioSmsProvider()
        proveedor._client = cliente

        proveedor.send("+59170000000", "codigo 654321")

        cliente.messages.create.assert_called_once()
        kwargs = cliente.messages.create.call_args.kwargs
        self.assertEqual(kwargs["to"], "+59170000000")
        self.assertEqual(kwargs["from_"], settings.TWILIO_FROM_NUMBER)
        self.assertIn("654321", kwargs["body"])

    def test_twilio_devuelve_none_para_no_viajar_el_codigo(self):
        settings.SMS_PROVIDER = "twilio"
        proveedor = MagicMock()
        with patch.object(sms_module, "get_sms_provider", return_value=proveedor):
            codigo = send_password_reset_sms("+59170000000", "123456")

        self.assertIsNone(codigo)

    # ------------------------------------------------------------------ #
    # 4.4 Fallo del proveedor
    # ------------------------------------------------------------------ #
    def test_fallo_del_proveedor_no_propaga_la_excepcion(self):
        settings.SMS_PROVIDER = "twilio"
        proveedor = MagicMock()
        proveedor.send.side_effect = RuntimeError("credencial invalida")
        with patch.object(sms_module, "get_sms_provider", return_value=proveedor):
            codigo = send_password_reset_sms("+59170000000", "123456")

        self.assertIsNone(codigo)

    # ------------------------------------------------------------------ #
    # 4.3 Endpoint forgot-password con canal
    # ------------------------------------------------------------------ #
    def test_endpoint_sms_usa_el_proveedor_configurado(self):
        settings.SMS_PROVIDER = "console"
        proveedor = MagicMock()
        with patch.object(sms_module, "get_sms_provider", return_value=proveedor):
            response = self.client.post(
                "/auth/forgot-password",
                json={"correo": "con.telefono@ejemplo.com", "canal": "sms"},
            )

        self.assertEqual(response.status_code, 200)
        proveedor.send.assert_called_once()
        self.assertEqual(proveedor.send.call_args[0][0], "+59170000000")

    def test_endpoint_sin_canal_usa_correo_por_defecto(self):
        settings.SMS_PROVIDER = "console"
        proveedor = MagicMock()
        with patch.object(sms_module, "get_sms_provider", return_value=proveedor):
            with patch("app.modules.auth.service.send_password_reset_email") as correo:
                correo.return_value = None
                response = self.client.post(
                    "/auth/forgot-password",
                    json={"correo": "con.telefono@ejemplo.com"},
                )

        self.assertEqual(response.status_code, 200)
        correo.assert_called_once()
        proveedor.send.assert_not_called()

    def test_usuario_sin_telefono_responde_el_mismo_mensaje_generico(self):
        settings.SMS_PROVIDER = "console"
        proveedor = MagicMock()
        with patch.object(sms_module, "get_sms_provider", return_value=proveedor):
            response = self.client.post(
                "/auth/forgot-password",
                json={"correo": "sin.telefono@ejemplo.com", "canal": "sms"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], GENERICO)
        # El campo viaja como null; lo relevante es que no haya ningun codigo.
        self.assertIsNone(response.json()["debug_code"])
        proveedor.send.assert_not_called()

    def test_correo_no_registrado_responde_el_mismo_mensaje_generico(self):
        settings.SMS_PROVIDER = "console"
        proveedor = MagicMock()
        with patch.object(sms_module, "get_sms_provider", return_value=proveedor):
            response = self.client.post(
                "/auth/forgot-password",
                json={"correo": "noexiste@externo.com", "canal": "sms"},
            )

        # Indistinguible del usuario sin telefono: es el escenario anti-enumeración.
        self.assertEqual(response.json()["detail"], GENERICO)
        proveedor.send.assert_not_called()

    def test_fallo_del_proveedor_no_rompe_el_endpoint(self):
        settings.SMS_PROVIDER = "twilio"
        proveedor = MagicMock()
        proveedor.send.side_effect = RuntimeError("fallo de red")
        with patch.object(sms_module, "get_sms_provider", return_value=proveedor):
            response = self.client.post(
                "/auth/forgot-password",
                json={"correo": "con.telefono@ejemplo.com", "canal": "sms"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], GENERICO)

    def test_canal_invalido_es_rechazado(self):
        response = self.client.post(
            "/auth/forgot-password",
            json={"correo": "con.telefono@ejemplo.com", "canal": "telegram"},
        )
        self.assertEqual(response.status_code, 422)

    # ------------------------------------------------------------------ #
    # 4.4 Sin credenciales en el repositorio
    # ------------------------------------------------------------------ #
    def test_no_hay_credenciales_de_twilio_en_el_codigo(self):
        """Las credenciales deben venir solo de settings, nunca del código."""
        with open(sms_module.__file__, encoding="utf-8") as fh:
            contenido = fh.read()

        # Un SID real de Twilio empieza por "AC" seguido de 32 hexadecimales.
        import re

        self.assertIsNone(
            re.search(r"AC[0-9a-fA-F]{32}", contenido),
            "hay un SID de Twilio escrito en el codigo",
        )
        self.assertNotIn("api_key", contenido)
        # Y ambas credenciales deben leerse de la configuracion.
        self.assertIn("settings.TWILIO_ACCOUNT_SID", contenido)
        self.assertIn("settings.TWILIO_AUTH_TOKEN", contenido)


if __name__ == "__main__":
    unittest.main()
