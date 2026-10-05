"""Cierre global de sesion y revocacion de tokens (CU24).

La diferencia con el cierre por inactividad de CU23 es que aqui se cierran
TODAS las sesiones del usuario en todos los dispositivos, incrementando
`token_version`.
"""
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from app.main import app
from app.modules.auth.models import SesionActiva, TokenBlacklist, Usuario
from app.modules.auth.session_service import is_revoked

ID_CLINICA_PRUEBA = 7


class TestCierreSesionGlobalCU24(unittest.TestCase):
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
            # Cada prueba empieza en token_version 0.
            db.query(Usuario).filter_by(id_usuario=1).update({"token_version": 0})
            db.commit()
        finally:
            db.close()

    def _crear_sesion(self, jti: str, id_usuario: int = 1) -> None:
        db = self.SessionLocal()
        try:
            ahora = datetime.now(timezone.utc)
            db.add(
                SesionActiva(
                    jti=jti,
                    id_usuario=id_usuario,
                    id_clinica=ID_CLINICA_PRUEBA,
                    creada_en=ahora,
                    ultima_actividad=ahora,
                )
            )
            db.commit()
        finally:
            db.close()

    def _refresh(self, jti: str, token_version: int = 0) -> str:
        return create_refresh_token(
            {"sub": "1", "jti": jti, "token_version": token_version}
        )

    def _access(self, jti: str, token_version: int = 0) -> str:
        return create_access_token({"sub": "1", "jti": jti, "token_version": token_version})

    # ------------------------------------------------------------------ #
    # Escenario del spec: cierre de sesion manual exitoso
    # ------------------------------------------------------------------ #
    def test_logout_responde_204_e_incrementa_token_version(self):
        self._crear_sesion("jti-logout")

        respuesta = self.client.post(
            "/auth/logout", json={"refresh_token": self._refresh("jti-logout")}
        )

        self.assertEqual(respuesta.status_code, 204)
        db = self.SessionLocal()
        try:
            usuario = db.query(Usuario).filter_by(id_usuario=1).one()
            self.assertEqual(usuario.token_version, 1)
        finally:
            db.close()

    def test_logout_invalida_el_access_token_previo(self):
        self._crear_sesion("jti-logout")
        access = self._access("jti-logout")
        headers = {"Authorization": f"Bearer {access}"}

        # Antes del logout el token sirve.
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 200)

        self.client.post("/auth/logout", json={"refresh_token": self._refresh("jti-logout")})

        # Despues del logout, el mismo token deja de servir.
        respuesta = self.client.get("/auth/me", headers=headers)
        self.assertEqual(respuesta.status_code, 401)
        self.assertIn("Sesion cerrada", respuesta.json()["detail"])

    def test_logout_invalida_el_refresh_previo(self):
        self._crear_sesion("jti-logout")
        refresh = self._refresh("jti-logout")

        self.client.post("/auth/logout", json={"refresh_token": refresh})

        respuesta = self.client.post("/auth/refresh", json={"refresh_token": refresh})
        self.assertEqual(respuesta.status_code, 401)

    def test_logout_revoca_la_sesion(self):
        self._crear_sesion("jti-logout")

        self.client.post("/auth/logout", json={"refresh_token": self._refresh("jti-logout")})

        db = self.SessionLocal()
        try:
            self.assertTrue(is_revoked(db, "jti-logout"))
        finally:
            db.close()

    def test_logout_es_idempotente(self):
        """Cerrar dos veces responde 204 ambas veces y no sigue incrementando."""
        self._crear_sesion("jti-logout")
        refresh = self._refresh("jti-logout")

        self.assertEqual(
            self.client.post("/auth/logout", json={"refresh_token": refresh}).status_code, 204
        )
        self.assertEqual(
            self.client.post("/auth/logout", json={"refresh_token": refresh}).status_code, 204
        )

        db = self.SessionLocal()
        try:
            # Solo se incremento una vez: tras el logout, el refresh ya no resuelve
            # usuario, asi que el segundo logout no vuelve a incrementar.
            self.assertEqual(db.query(Usuario).filter_by(id_usuario=1).one().token_version, 1)
        finally:
            db.close()

    def test_logout_con_token_invalido_responde_204(self):
        """Un logout nunca debe fallar: el cliente limpia su almacenamiento igual."""
        respuesta = self.client.post("/auth/logout", json={"refresh_token": "no-es-un-jwt"})
        self.assertEqual(respuesta.status_code, 204)

    # ------------------------------------------------------------------ #
    # Renovacion: la sesion debe sobrevivir al refresh
    # ------------------------------------------------------------------ #
    def test_refresh_conserva_el_jti_de_la_sesion(self):
        """Si el refresh emitiera un jti nuevo, la sesion se escaparia del
        control de inactividad de CU23 (no tendria fila en sesiones_activas)."""
        self._crear_sesion("jti-fresh")

        respuesta = self.client.post(
            "/auth/refresh", json={"refresh_token": self._refresh("jti-fresh")}
        )

        self.assertEqual(respuesta.status_code, 200)
        payload = decode_access_token(respuesta.json()["access_token"])
        self.assertEqual(payload["jti"], "jti-fresh")
        self.assertEqual(payload["token_version"], 0)

        db = self.SessionLocal()
        try:
            self.assertIsNotNone(db.query(SesionActiva).filter_by(jti="jti-fresh").one())
        finally:
            db.close()

    def test_refresh_tras_logout_falla_por_token_version(self):
        self._crear_sesion("jti-fresh")
        refresh = self._refresh("jti-fresh")

        self.client.post("/auth/logout", json={"refresh_token": refresh})
        respuesta = self.client.post("/auth/refresh", json={"refresh_token": refresh})

        self.assertEqual(respuesta.status_code, 401)

    def test_token_antiguo_a_cu24_sigue_aceptandose(self):
        """Compatibilidad: los tokens emitidos antes de este requisito no
        llevan el claim `token_version` y no deben expulsar a las sesiones vivas."""
        self._crear_sesion("jti-legacy")
        access = create_access_token({"sub": "1", "jti": "jti-legacy"})

        respuesta = self.client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})

        self.assertEqual(respuesta.status_code, 200)


if __name__ == "__main__":
    unittest.main()