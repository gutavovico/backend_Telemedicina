"""CU16 - Bloqueo de integración de roles: GET /auth/me expone `rol` oficial.

Contrato oficial: backend/specs/openspec/contracts/auth.md §2.7.
`rol: string | null` es el nombre real de la relación Usuario.rol.
`id_rol` se mantiene solo por compatibilidad y nunca decide permisos.

Estas pruebas usan IDs de rol no habituales para demostrar que la
respuesta no depende del número del rol, del correo ni del nombre.
Usa únicamente la base local de pruebas (sqlite en memoria).
"""
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import joinedload, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


class CU16AuthMeRolTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
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
        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        self._reset_data()

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _reset_data(self):
        with self.engine.begin() as conn:
            for table in ("usuarios", "roles", "clinicas"):
                try:
                    conn.exec_driver_sql(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'Clinica Central', 'ACTIVO')"
            )
            # IDs deliberadamente no habituales: la respuesta no debe depender del número.
            conn.exec_driver_sql(
                "INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES "
                "(91, 1, 'ADMIN', 'ACTIVO'), "
                "(52, 1, 'MEDICO', 'ACTIVO'), "
                "(73, 1, 'PACIENTE', 'ACTIVO'), "
                "(1, 1, 'PACIENTE', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                """INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos,
                   correo, password_hash, estado, token_version,
                   notificaciones_push, notificaciones_email, notificaciones_sms) VALUES
                (11, 1, 91, 'Ada', 'Lovelace', 'ada.lovelace@clinica.bo', 'hash', 'activo', 0, 1, 1, 0),
                (12, 1, 52, 'Carlos', 'Mendoza', 'carlos.mendoza@salud.bo', 'hash', 'activo', 0, 1, 1, 0),
                (13, 1, 73, 'Maria', 'Rojas', 'maria.rojas@example.com', 'hash', 'activo', 0, 1, 1, 0),
                (14, 1, NULL, 'Sin', 'Rol', 'sin.rol@clinica.bo', 'hash', 'activo', 0, 1, 1, 0),
                (15, 1, 1, 'Pedro', 'Paredes', 'pedro.paredes@clinica.bo', 'hash', 'activo', 0, 1, 1, 0)"""
            )

    def _auth_as(self, user_id: int):
        db = self.SessionLocal()
        try:
            user = (
                db.query(Usuario)
                .options(joinedload(Usuario.rol))
                .filter(Usuario.id_usuario == user_id)
                .first()
            )
            assert user is not None
            db.expunge(user)
            # Expulsar también el rol cargado para que la serialización no dependa de la sesión.
            try:
                db.expunge(user.rol)
            except Exception:
                pass
        finally:
            db.close()
        app.dependency_overrides[get_current_user] = lambda: user

    def _get_me(self, user_id: int):
        self._auth_as(user_id)
        resp = self.client.get("/auth/me")
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_me_devuelve_admin_real_sin_depender_del_numero(self):
        body = self._get_me(11)
        self.assertEqual(body["rol"], "ADMIN")
        self.assertEqual(body["id_rol"], 91)
        self.assertEqual(body["correo"], "ada.lovelace@clinica.bo")

    def test_me_devuelve_medico_real_sin_depender_del_numero(self):
        body = self._get_me(12)
        self.assertEqual(body["rol"], "MEDICO")
        self.assertEqual(body["id_rol"], 52)

    def test_me_devuelve_paciente_real_sin_depender_del_numero(self):
        body = self._get_me(13)
        self.assertEqual(body["rol"], "PACIENTE")
        self.assertEqual(body["id_rol"], 73)

    def test_me_sin_rol_devuelve_null_y_mantiene_id_rol(self):
        body = self._get_me(14)
        self.assertIsNone(body["rol"])
        self.assertIsNone(body["id_rol"])

    def test_me_id_1_no_concede_admin_si_el_nombre_real_no_es_admin(self):
        # id_rol == 1 pero el rol real es PACIENTE: no hay IDs mágicos.
        body = self._get_me(15)
        self.assertEqual(body["id_rol"], 1)
        self.assertEqual(body["rol"], "PACIENTE")
        self.assertNotEqual(body["rol"], "ADMIN")


if __name__ == "__main__":
    unittest.main()
