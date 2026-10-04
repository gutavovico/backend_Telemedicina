"""Pruebas del contrato de autenticacion compartido por Angular y Flutter.

Los guards por rol de los clientes (CU12 documentoAccessGuard, CU23) dependen de
que `GET /auth/me` exponga `rol`. Antes de anadirlo, `UsuarioResponse` no lo
serializaba, por lo que `userRole()` devolvia siempre null en el frontend y
toda ruta restringida por rol redirigia al inicio. Estas pruebas fijan el
contrato para evitar la regresión.
"""
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


class AuthContractTestCase(unittest.TestCase):
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
        app.dependency_overrides.pop(get_current_user, None)

    @classmethod
    def _create_schema(cls):
        with cls.engine.begin() as conn:
            conn.exec_driver_sql("""
                CREATE TABLE clinicas (
                    id_clinica INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    razon_social TEXT NULL,
                    nit TEXT NULL,
                    telefono TEXT NULL,
                    correo TEXT NULL,
                    direccion TEXT NULL,
                    logo TEXT NULL,
                    estado TEXT NOT NULL DEFAULT 'ACTIVO',
                    fecha_creacion TIMESTAMP NULL
                )
            """)
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
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre) VALUES (1, 'Clinica Uno')"
            )
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, nombre, estado) VALUES "
                "(1, 'ADMIN', 'ACTIVO'),"
                "(2, 'MEDICO', 'ACTIVO'),"
                "(3, 'RECEPCION', 'ACTIVO'),"
                "(4, 'PACIENTE', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, "
                "password_hash, estado, notificaciones_push, notificaciones_email, notificaciones_sms) VALUES "
                "(1, 1, 2, 'Ana', 'Perez', 'ana@ejemplo.com', 'x', 'ACTIVO', 1, 1, 0)"
            )

    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _override_current_user(self, user_id: int):
        def dependency():
            db: Session = self.SessionLocal()
            try:
                return db.get(Usuario, user_id)
            finally:
                db.close()

        app.dependency_overrides[get_current_user] = dependency

    # ------------------------------------------------------------------ #
    # Tests
    # ------------------------------------------------------------------ #
    def test_me_expone_rol_id_rol_e_id_clinica(self):
        """Regresión: los guards por rol del frontend dependían de estos campos."""
        self._override_current_user(1)
        response = self.client.get("/auth/me")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["rol"], "MEDICO")
        self.assertEqual(body["id_rol"], 2)
        self.assertEqual(body["id_clinica"], 1)

    def test_model_rol_expone_el_nombre_del_rol(self):
        db = self.SessionLocal()
        try:
            usuario = db.get(Usuario, 1)
            self.assertEqual(usuario.rol, "MEDICO")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
