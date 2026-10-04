"""Pruebas de identidad de sesion: emision de `jti` y `token_version` (CU23).

Sin un identificador de sesion no hay forma de revocar una sesion concreta sin
cerrar todas las del usuario, que es el requisito central del control de
inactividad. CU01 ya exigia el claim `token_version`, que el codigo no emitia.
Estas pruebas fijan ambos claims y el registro de la fila de sesion.
"""
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    new_jti,
)
from app.main import app
from app.modules.auth.models import SesionActiva, Usuario


class SessionIdentityTestCase(unittest.TestCase):
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
            # `Usuario.rol_rel` usa lazy="joined", asi que el login trae un JOIN
            # contra roles y la tabla debe existir.
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
                "INSERT INTO roles (id_rol, nombre, estado) VALUES (2, 'MEDICO', 'ACTIVO')"
            )
            # Tabla sesion del esquema de la migracion 005.
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
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, "
                "correo, telefono, password_hash, estado, notificaciones_push, "
                "notificaciones_email, notificaciones_sms, token_version) VALUES "
                "(1, 7, 2, 'Ana', 'Perez', 'ana@ejemplo.com', '+59170000000', "
                f"'{hash_password('secreta123')}', 'ACTIVO', 1, 1, 0, 0)"
            )

    def setUp(self):
        self.client = TestClient(app)
        db = self.SessionLocal()
        try:
            db.query(SesionActiva).delete()
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # 2.1 Emision de claims
    # ------------------------------------------------------------------ #
    def test_access_token_lleva_jti_y_token_version(self):
        token = create_access_token({"sub": "1", "token_version": 3})
        payload = decode_access_token(token)

        self.assertIn("jti", payload)
        self.assertEqual(payload["token_version"], 3)

    def test_refresh_token_lleva_jti_y_token_version(self):
        token = create_refresh_token({"sub": "1", "token_version": 3})
        payload = decode_refresh_token(token)

        self.assertIn("jti", payload)
        self.assertEqual(payload["token_version"], 3)

    def test_par_de_tokens_comparte_un_unico_jti(self):
        """Acceso y refresh deben identificar la MISMA sesion."""
        payload = {"sub": "1"}
        acceso = decode_access_token(create_access_token(payload))
        refresh = decode_refresh_token(create_refresh_token({**payload, "jti": acceso["jti"]}))

        self.assertEqual(acceso["jti"], refresh["jti"])

    def test_new_jti_es_unico_y_hexadecimal(self):
        self.assertNotEqual(new_jti(), new_jti())
        # Debe caber en el VARCHAR(64) del esquema desplegado.
        self.assertLessEqual(len(new_jti()), 64)
        uuid.UUID(hex=new_jti())

    # ------------------------------------------------------------------ #
    # 2.2 Compatibilidad hacia atras
    # ------------------------------------------------------------------ #
    def test_token_sin_jti_se_sigue_aceptando(self):
        """Los tokens emitidos antes de este cambio no deben expulsar de golpe."""
        from datetime import datetime, timedelta, timezone
        from jose import jwt
        from app.core.config import settings

        legacy = jwt.encode(
            {
                "sub": "1",
                "email": "ana@ejemplo.com",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
                "type": "access",
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

        payload = decode_access_token(legacy)
        self.assertIsNone(payload.get("jti"))

    # ------------------------------------------------------------------ #
    # 2.3 / 2.4 Registro de la sesion en el login
    # ------------------------------------------------------------------ #
    def test_login_registra_la_sesion_con_el_jti_del_token(self):
        response = self.client.post(
            "/auth/login",
            json={"correo": "ana@ejemplo.com", "password": "secreta123"},
        )

        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]
        jti = decode_access_token(token)["jti"]

        db = self.SessionLocal()
        try:
            sesion = db.query(SesionActiva).filter_by(jti=jti).one_or_none()
            self.assertIsNotNone(sesion, "el login debe crear la fila de sesion")
            self.assertEqual(sesion.id_usuario, 1)
            self.assertEqual(sesion.id_clinica, 7)
            self.assertIsNone(sesion.revocada_en)
        finally:
            db.close()

    def test_login_incorpora_el_token_version_del_usuario(self):
        db = self.SessionLocal()
        try:
            usuario = db.get(Usuario, 1)
            usuario.token_version = 5
            db.commit()
        finally:
            db.close()

        response = self.client.post(
            "/auth/login",
            json={"correo": "ana@ejemplo.com", "password": "secreta123"},
        )

        payload = decode_access_token(response.json()["access_token"])
        self.assertEqual(payload["token_version"], 5)

        db = self.SessionLocal()
        try:
            db.get(Usuario, 1).token_version = 0
            db.commit()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
