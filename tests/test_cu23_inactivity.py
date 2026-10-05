"""Pruebas del control de inactividad por sesión (CU23).

Cubren los escenarios Gherkin de la delta del change
`cu23-recuperacion-contrasena-cierre-automatico`: rechazo tras superar la
ventana, refresco de la marca dentro de la ventana, no afectacion de otras
sesiones del mismo usuario, segundos restantes y purga de revocaciones.

Se opera el tiempo con `now=` explicito en lugar de dormir: esperar 15 minutos
reales haria la suite inutilizable y `freezegun` no es una dependencia del
proyecto.
"""
import unittest
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token
from app.main import app
from app.modules.auth.models import SesionActiva, TokenBlacklist, Usuario
from app.modules.auth.session_service import (
    _as_utc,
    enforce_inactivity,
    is_revoked,
    purge_expired_revocations,
    revoke_session,
    session_status,
)

VENTANA = settings.INACTIVITY_TIMEOUT_MINUTES * 60
ID_CLINICA_PRUEBA = 7


class InactivityTestCase(unittest.TestCase):
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
                CREATE TABLE roles (
                    id_rol INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_clinica INTEGER NULL,
                    nombre TEXT NOT NULL,
                    descripcion TEXT NULL,
                    estado TEXT NOT NULL,
                    fecha_creacion TIMESTAMP NULL
                )
            """)
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
            conn.exec_driver_sql("""
                CREATE TABLE sesiones_activas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    jti VARCHAR(64) NOT NULL UNIQUE,
                    id_usuario BIGINT NOT NULL,
                    id_clinica BIGINT NULL,
                    creada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ultima_actividad TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    revocada_en TIMESTAMP NULL
                )
            """)
            # Tabla preexistente del esquema desplegado.
            conn.exec_driver_sql("""
                CREATE TABLE token_blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token VARCHAR(500) NOT NULL,
                    revoked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, nombre, estado) VALUES (2, 'MEDICO', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, "
                "correo, password_hash, estado, notificaciones_push, notificaciones_email, "
                "notificaciones_sms, token_version) VALUES "
                "(1, 7, 2, 'Ana', 'Perez', 'ana@ejemplo.com', 'x', 'ACTIVO', 1, 1, 0, 0)"
            )

    def setUp(self):
        self.client = TestClient(app)
        db = self.SessionLocal()
        try:
            db.query(TokenBlacklist).delete()
            db.query(SesionActiva).delete()
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _crear_sesion(self, jti: str, minutos_inactiva: int, id_usuario: int = 1) -> None:
        db = self.SessionLocal()
        try:
            ahora = datetime.now(timezone.utc)
            db.add(
                SesionActiva(
                    jti=jti,
                    id_usuario=id_usuario,
                    id_clinica=ID_CLINICA_PRUEBA,
                    creada_en=ahora,
                    ultima_actividad=ahora - timedelta(minutes=minutos_inactiva),
                    revocada_en=None,
                )
            )
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # 3.1 Refresco dentro de la ventana
    # ------------------------------------------------------------------ #
    def test_peticion_dentro_de_la_ventana_devuelve_segundos_restantes(self):
        self._crear_sesion("jti-activa", minutos_inactiva=2)

        db = self.SessionLocal()
        try:
            restante = enforce_inactivity(db, "jti-activa", 1)
        finally:
            db.close()

        self.assertIsNotNone(restante)
        self.assertGreater(restante, 0)
        self.assertLessEqual(restante, VENTANA)

    def test_peticion_con_actividad_refresca_la_marca(self):
        # Marca muy antigua, por debajo del intervalo minimo de escritura.
        self._crear_sesion("jti-refresco", minutos_inactiva=2)
        db = self.SessionLocal()
        try:
            antes = db.query(SesionActiva).filter_by(jti="jti-refresco").one().ultima_actividad
            ahora = datetime.now(timezone.utc) + timedelta(seconds=120)
            enforce_inactivity(db, "jti-refresco", 1, now=ahora)
            despues = (
                db.query(SesionActiva).filter_by(jti="jti-refresco").one().ultima_actividad
            )
        finally:
            db.close()

        self.assertGreater(despues, antes)

    # ------------------------------------------------------------------ #
    # 3.2 Rechazo tras superar la ventana
    # ------------------------------------------------------------------ #
    def test_peticion_tras_la_ventana_es_rechazada_con_401(self):
        self._crear_sesion("jti-vencida", minutos_inactiva=16)

        db = self.SessionLocal()
        try:
            with self.assertRaises(HTTPException) as ctx:
                enforce_inactivity(db, "jti-vencida", 1)
            self.assertEqual(ctx.exception.status_code, 401)
        finally:
            db.close()

    def test_sesion_vencida_queda_revocada_y_no_puede_volver(self):
        self._crear_sesion("jti-revocar", minutos_inactiva=16)

        db = self.SessionLocal()
        try:
            with self.assertRaises(HTTPException):
                enforce_inactivity(db, "jti-revocar", 1)

            revocada = db.query(TokenBlacklist).filter_by(token="jti-revocar").count()
            sesion = db.query(SesionActiva).filter_by(jti="jti-revocar").one()
        finally:
            db.close()

        self.assertEqual(revocada, 1, "el jti debe quedar en token_blacklist")
        self.assertIsNotNone(sesion.revocada_en)

        # Segunda peticion posterior: tambien rechazada.
        db = self.SessionLocal()
        try:
            with self.assertRaises(HTTPException):
                enforce_inactivity(db, "jti-revocar", 1)
        finally:
            db.close()

    def test_token_sin_jti_no_se_rechaza_por_inactividad(self):
        """Compatibilidad: los tokens previos no tienen jti ni sesion registrada."""
        db = self.SessionLocal()
        try:
            self.assertIsNone(enforce_inactivity(db, None, 1))
            self.assertIsNone(enforce_inactivity(db, "jti-inexistente", 1))
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # 3.3 El cierre no afecta a otras sesiones del mismo usuario
    # ------------------------------------------------------------------ #
    def test_sesion_vencida_no_afecta_a_otra_activa_del_mismo_usuario(self):
        self._crear_sesion("jti-movil", minutos_inactiva=16)
        self._crear_sesion("jti-portatil", minutos_inactiva=1)

        db = self.SessionLocal()
        try:
            with self.assertRaises(HTTPException):
                enforce_inactivity(db, "jti-movil", 1)

            # El portatil sigue vivo.
            restante = enforce_inactivity(db, "jti-portatil", 1)
        finally:
            db.close()

        self.assertGreater(restante, 0)

    # ------------------------------------------------------------------ #
    # 3.4 Segundos restantes
    # ------------------------------------------------------------------ #
    def test_segundos_restantes_nunca_superan_la_ventana(self):
        self._crear_sesion("jti-reciente", minutos_inactiva=0)
        db = self.SessionLocal()
        try:
            estado = session_status(db, "jti-reciente", 1)
        finally:
            db.close()

        self.assertGreater(estado["segundos_restantes"], 0)
        self.assertLessEqual(estado["segundos_restantes"], VENTANA)

    def test_segundos_restantes_decaen_con_el_tiempo(self):
        self._crear_sesion("jti-decreciente", minutos_inactiva=1)
        db = self.SessionLocal()
        try:
            temprano = session_status(db, "jti-decreciente", 1)["segundos_restantes"]
            db.query(SesionActiva).filter_by(jti="jti-decreciente").update(
                {"ultima_actividad": datetime.now(timezone.utc) - timedelta(minutes=10)}
            )
            db.commit()
            tarde = session_status(db, "jti-decreciente", 1)["segundos_restantes"]
        finally:
            db.close()

        self.assertLess(tarde, temprano)

    def test_endpoint_session_devuelve_el_tiempo_restante(self):
        self._crear_sesion("jti-endpoint", minutos_inactiva=3)
        token = create_access_token({"sub": "1", "jti": "jti-endpoint", "token_version": 0})

        response = self.client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("segundos_restantes", body)
        self.assertEqual(body["ventana_segundos"], VENTANA)
        self.assertEqual(body["aviso_segundos"], settings.INACTIVITY_WARNING_SECONDS)
        self.assertLessEqual(body["segundos_restantes"], VENTANA)

    def test_consultar_el_estado_no_renueva_la_sesion(self):
        """Consultar el reloj no puede usarse para alargar la sesion (CU23).

        Si `GET /auth/session` refrescara `ultima_actividad`, un cliente que
        solo pregunte por su estado se mantendria vivo indefinidamente.
        """
        self._crear_sesion("jti-consulta", minutos_inactiva=5)
        token = create_access_token({"sub": "1", "jti": "jti-consulta", "token_version": 0})

        primero = self.client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(primero.status_code, 200)

        db = self.SessionLocal()
        try:
            sesion = db.query(SesionActiva).filter_by(jti="jti-consulta").one()
            marca_antes = _as_utc(sesion.ultima_actividad)
        finally:
            db.close()

        segundo = self.client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(segundo.status_code, 200)

        db = self.SessionLocal()
        try:
            marca_despues = _as_utc(
                db.query(SesionActiva).filter_by(jti="jti-consulta").one().ultima_actividad
            )
        finally:
            db.close()

        self.assertEqual(marca_antes, marca_despues)
        # El tiempo restante tampoco se reinicia.
        self.assertAlmostEqual(
            primero.json()["segundos_restantes"],
            segundo.json()["segundos_restantes"],
            delta=2,
        )

    def test_estado_de_sesion_revocada_devuelve_401(self):
        """Una sesion revocada no puede anunciar una ventana que el servidor no respeta."""
        self._crear_sesion("jti-revocada-consulta", minutos_inactiva=1)
        token = create_access_token(
            {"sub": "1", "jti": "jti-revocada-consulta", "token_version": 0}
        )
        db = self.SessionLocal()
        try:
            revoke_session(db, "jti-revocada-consulta")
        finally:
            db.close()

        response = self.client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)

    def test_continue_renueva_la_actividad_en_el_servidor(self):
        """El boton 'Seguir conectado' debe renovar la sesion en el servidor."""
        self._crear_sesion("jti-continuar", minutos_inactiva=5)
        token = create_access_token({"sub": "1", "jti": "jti-continuar", "token_version": 0})

        antes = self.client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(antes.status_code, 200)

        respuesta = self.client.post(
            "/auth/session/continue", headers={"Authorization": f"Bearer {token}"}
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertGreater(
            respuesta.json()["segundos_restantes"], antes.json()["segundos_restantes"]
        )
        # Tras renovar queda practicamente la ventana completa (se trunca a
        # segundos enteros, asi que puede quedar en 899).
        self.assertAlmostEqual(
            respuesta.json()["segundos_restantes"], VENTANA, delta=2
        )

    def test_continue_sobre_sesion_vencida_devuelve_401(self):
        self._crear_sesion(
            "jti-continuar-vencida",
            minutos_inactiva=settings.INACTIVITY_TIMEOUT_MINUTES + 1,
        )
        token = create_access_token(
            {"sub": "1", "jti": "jti-continuar-vencida", "token_version": 0}
        )

        respuesta = self.client.post(
            "/auth/session/continue", headers={"Authorization": f"Bearer {token}"}
        )

        self.assertEqual(respuesta.status_code, 401)

    def test_sesion_de_otra_clinica_se_invalida(self):
        """Una sesion abierta no sobrevive a un cambio de clinica del usuario.

        Se prueba por la ruta real (`get_current_user`) porque ahi es donde se
        conoce el tenant actual del usuario y se puede comparar con el de la
        sesion.
        """
        self._crear_sesion("jti-cambio-clinica", minutos_inactiva=1)
        token = create_access_token(
            {"sub": "1", "jti": "jti-cambio-clinica", "token_version": 0}
        )

        # Antes del cambio la sesion sirve con normalidad.
        self.assertEqual(
            self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code,
            200,
        )

        # El usuario cambio de clinica con la sesion abierta.
        db = self.SessionLocal()
        try:
            db.query(Usuario).filter_by(id_usuario=1).update({"id_clinica": 99})
            db.commit()
        finally:
            db.close()

        respuesta = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(respuesta.status_code, 401)
        db = self.SessionLocal()
        try:
            self.assertTrue(is_revoked(db, "jti-cambio-clinica"))
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # 3.5 Purga de revocaciones
    # ------------------------------------------------------------------ #
    def test_purga_no_borra_revocaciones_vigentes(self):
        self._crear_sesion("jti-vigente", minutos_inactiva=0)
        db = self.SessionLocal()
        try:
            revoke_session(db, "jti-vigente")
            purge_expired_revocations(db)
            restantes = db.query(TokenBlacklist).count()
        finally:
            db.close()

        self.assertEqual(restantes, 1, "una revocacion reciente debe conservarse")

    def test_purga_borra_lo_que_ya_no_rechaza_nada(self):
        viejo = datetime.now(timezone.utc) - timedelta(days=30)
        db = self.SessionLocal()
        try:
            db.add(
                SesionActiva(
                    jti="jti-obsoleto",
                    id_usuario=1,
                    id_clinica=7,
                    creada_en=viejo,
                    ultima_actividad=viejo,
                    revocada_en=viejo,
                )
            )
            db.add(TokenBlacklist(token="jti-obsoleto", revocada_en=viejo))
            db.commit()

            purge_expired_revocations(db)

            self.assertEqual(db.query(TokenBlacklist).filter_by(token="jti-obsoleto").count(), 0)
            self.assertEqual(db.query(SesionActiva).filter_by(jti="jti-obsoleto").count(), 0)
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Integracion con la dependencia de autenticacion
    # ------------------------------------------------------------------ #
    def test_peticion_autenticada_con_sesion_vencida_devuelve_401(self):
        self._crear_sesion("jti-http", minutos_inactiva=16)
        token = create_access_token({"sub": "1", "jti": "jti-http", "token_version": 0})

        response = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("inactividad", response.json()["detail"])

    def test_peticion_autenticada_con_sesion_viva_devuelve_200(self):
        self._crear_sesion("jti-http-ok", minutos_inactiva=1)
        token = create_access_token({"sub": "1", "jti": "jti-http-ok", "token_version": 0})

        response = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(decode_access_token(token)["jti"], "jti-http-ok")


if __name__ == "__main__":
    unittest.main()
