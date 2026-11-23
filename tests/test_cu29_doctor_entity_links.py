"""CU29: pruebas de integración de vinculación médico-entidad.

Usan una base SQLite real compartida por el motor síncrono (rutas legacy) y el
motor asíncrono (`aiosqlite`, rutas CU29). No hay mocks de base de datos.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import Base, get_async_db, get_db
from app.core.security import hash_password
from app.main import app
from app.modules.appointments.doctor_entity_links.models import (
    CredencialTemporalMedico,
    HistorialVinculacionMedico,
    VinculacionMedicoEntidad,
    VinculacionMedicoEspecialidad,
    VinculacionMedicoRol,
    VinculacionMedicoSede,
)
from app.modules.appointments.models import (
    Cita,
    Especialidad,
    Medico,
    MedicoEspecialidad,
)
from app.modules.auth.dependencies import (
    get_current_user,
    get_current_user_allow_password_change,
)
from app.modules.auth.models import (
    Auditoria,
    Clinica,
    Permiso,
    Rol,
    RolPermiso,
    Usuario,
)
from app.modules.auth.service import authenticate_user
from app.modules.tenants.models import Sede
from app.modules.tenants.temporary_credentials import user_must_change_password

API = "/api/v1/medicos/vinculaciones"
LEGACY = "/medicos/vinculaciones"


class CU29DoctorEntityLinksTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="cu29-")
        cls.db_path = os.path.join(cls.tmpdir, "cu29.db")
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}",
            connect_args={"check_same_thread": False},
        )
        cls.SessionLocal = sessionmaker(
            bind=cls.engine, autocommit=False, autoflush=False
        )
        cls.async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{cls.db_path}"
        )
        cls.AsyncSessionLocal = async_sessionmaker(
            bind=cls.async_engine, expire_on_commit=False
        )

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        async def override_get_async_db():
            async with cls.AsyncSessionLocal() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_async_db] = override_get_async_db
        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        import asyncio

        asyncio.run(cls.async_engine.dispose())
        try:
            os.remove(cls.db_path)
            os.rmdir(cls.tmpdir)
        except OSError:
            pass

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self._sembrar()

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(
            get_current_user_allow_password_change, None
        )

    # ------------------------------------------------------------------ seed
    def _sembrar(self):
        with self.SessionLocal() as db:
            db.add_all(
                [
                    Clinica(id_clinica=1, nombre="Clínica Uno", estado="ACTIVO"),
                    Clinica(id_clinica=2, nombre="Clínica Dos", estado="ACTIVO"),
                ]
            )
            db.add_all(
                [
                    Rol(id_rol=1, id_clinica=None, nombre="ADMIN", estado="ACTIVO"),
                    Rol(id_rol=2, id_clinica=None, nombre="MEDICO", estado="ACTIVO"),
                    Rol(id_rol=3, id_clinica=1, nombre="ADMIN", estado="ACTIVO"),
                    Rol(id_rol=4, id_clinica=2, nombre="ADMIN", estado="ACTIVO"),
                    Rol(
                        id_rol=5,
                        id_clinica=None,
                        nombre="Super Administrador",
                        estado="ACTIVO",
                    ),
                    Rol(
                        id_rol=6,
                        id_clinica=1,
                        nombre="MEDICO_ESPECIALISTA",
                        estado="ACTIVO",
                    ),
                    Rol(
                        id_rol=7,
                        id_clinica=2,
                        nombre="MEDICO",
                        estado="ACTIVO",
                    ),
                    Rol(id_rol=8, id_clinica=1, nombre="RECEPCION", estado="ACTIVO"),
                    Rol(id_rol=9, id_clinica=None, nombre="PACIENTE", estado="ACTIVO"),
                ]
            )
            db.add_all(
                [
                    Permiso(
                        id_permiso=1,
                        nombre="medicos:read",
                        modulo="medicos",
                        accion="read",
                        estado="ACTIVO",
                    ),
                    Permiso(
                        id_permiso=2,
                        nombre="consultas:write",
                        modulo="consultas",
                        accion="write",
                        estado="ACTIVO",
                    ),
                    Permiso(
                        id_permiso=3,
                        nombre="recetas:read",
                        modulo="recetas",
                        accion="read",
                        estado="ACTIVO",
                    ),
                    Permiso(
                        id_permiso=4,
                        nombre="inactivo:test",
                        modulo="inactivo",
                        accion="test",
                        estado="INACTIVO",
                    ),
                    Permiso(
                        id_permiso=5,
                        nombre="prescriptions:read",
                        modulo="prescriptions",
                        accion="read",
                        estado="ACTIVO",
                    ),
                ]
            )
            db.add_all(
                [
                    RolPermiso(id_rol=2, id_permiso=1),
                    RolPermiso(id_rol=6, id_permiso=2),
                    RolPermiso(id_rol=7, id_permiso=3),
                    RolPermiso(id_rol=2, id_permiso=4),
                    RolPermiso(id_rol=2, id_permiso=5),
                ]
            )
            db.add_all(
                [
                    Usuario(
                        id_usuario=1,
                        id_clinica=1,
                        id_rol=3,
                        nombres="Admin",
                        apellidos="Uno",
                        correo="admin1@test.com",
                        password_hash="hash",
                        estado="activo",
                    ),
                    Usuario(
                        id_usuario=2,
                        id_clinica=2,
                        id_rol=4,
                        nombres="Admin",
                        apellidos="Dos",
                        correo="admin2@test.com",
                        password_hash="hash",
                        estado="activo",
                    ),
                    Usuario(
                        id_usuario=3,
                        id_clinica=1,
                        id_rol=2,
                        nombres="Médico",
                        apellidos="Uno",
                        correo="medico1@test.com",
                        documento_identidad="1111111 LP",
                        password_hash="hash",
                        estado="activo",
                    ),
                    Usuario(
                        id_usuario=4,
                        id_clinica=2,
                        id_rol=2,
                        nombres="Médico",
                        apellidos="Dos",
                        correo="medico2@test.com",
                        documento_identidad="2222222 CB",
                        password_hash="hash",
                        estado="activo",
                    ),
                    Usuario(
                        id_usuario=5,
                        id_clinica=None,
                        id_rol=5,
                        nombres="Súper",
                        apellidos="Admin",
                        correo="super@test.com",
                        password_hash="hash",
                        estado="activo",
                    ),
                    Usuario(
                        id_usuario=6,
                        id_clinica=None,
                        id_rol=1,
                        nombres="Admin",
                        apellidos="Global",
                        correo="adminglobal@test.com",
                        password_hash="hash",
                        estado="activo",
                    ),
                    Usuario(
                        id_usuario=7,
                        id_clinica=None,
                        id_rol=2,
                        nombres="Médico",
                        apellidos="Global",
                        correo="global@test.com",
                        documento_identidad="3333333 SC",
                        password_hash="hash",
                        estado="activo",
                    ),
                    Usuario(
                        id_usuario=8,
                        id_clinica=1,
                        id_rol=9,
                        nombres="Paciente",
                        apellidos="Uno",
                        correo="paciente@test.com",
                        password_hash="hash",
                        estado="activo",
                    ),
                ]
            )
            db.add_all(
                [
                    Especialidad(
                        id_especialidad=1,
                        nombre="Medicina General",
                        estado="activo",
                    ),
                    Especialidad(
                        id_especialidad=2, nombre="Cardiología", estado="activo"
                    ),
                    Especialidad(
                        id_especialidad=3, nombre="Inactiva", estado="inactivo"
                    ),
                ]
            )
            db.add_all(
                [
                    Medico(
                        id_medico=1,
                        id_usuario=3,
                        id_clinica=1,
                        matricula_profesional="MAT-A",
                        estado="activo",
                    ),
                    Medico(
                        id_medico=2,
                        id_usuario=4,
                        id_clinica=2,
                        matricula_profesional="MAT-B",
                        estado="activo",
                    ),
                ]
            )
            db.add(
                MedicoEspecialidad(
                    id_medico=1, id_especialidad=1, es_principal=True
                )
            )
            db.add_all(
                [
                    Sede(
                        id=1,
                        id_clinica=1,
                        nombre="Sede Central",
                        ubicacion="Centro",
                        activa=True,
                    ),
                    Sede(
                        id=2,
                        id_clinica=2,
                        nombre="Sede Dos",
                        ubicacion="Norte",
                        activa=True,
                    ),
                    Sede(
                        id=3,
                        id_clinica=1,
                        nombre="Sede Inactiva",
                        ubicacion="Sur",
                        activa=False,
                    ),
                ]
            )
            db.commit()

    # --------------------------------------------------------------- helpers
    def _as_user(self, id_usuario: int):
        def override(db: Session = Depends(get_db)):
            return db.scalars(
                select(Usuario)
                .options(joinedload(Usuario.rol_rel))
                .where(Usuario.id_usuario == id_usuario)
            ).first()

        app.dependency_overrides[get_current_user] = override

    def _as_password_change_user(self, id_usuario: int):
        def override(db: Session = Depends(get_db)):
            return db.scalars(
                select(Usuario)
                .options(joinedload(Usuario.rol_rel))
                .where(Usuario.id_usuario == id_usuario)
            ).first()

        app.dependency_overrides[get_current_user_allow_password_change] = override

    def _crear_existente(
        self,
        id_usuario: int,
        *,
        roles=None,
        principal=None,
        especialidades=None,
        sedes=None,
        expected=201,
    ):
        self._as_user(1)
        roles = roles or [2]
        principal = principal or roles[0]
        body = {
            "modo": "EXISTENTE",
            "id_usuario": id_usuario,
            "asignaciones": {
                "roles": roles,
                "id_rol_principal": principal,
                "especialidades": especialidades or [],
                "sedes": sedes or [],
            },
        }
        response = self.client.post(API, json=body)
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def _crear_nuevo(self, correo="nuevo@test.com", documento="9999999 LP", **kwargs):
        self._as_user(1)
        body = {
            "modo": "NUEVO",
            "usuario": {
                "nombres": "Nuevo",
                "apellidos": "Médico",
                "correo": correo,
                "telefono": "+591 70000000",
                "documento_identidad": documento,
            },
            "asignaciones": {
                "roles": kwargs.get("roles", [2]),
                "id_rol_principal": kwargs.get("principal", 2),
                "especialidades": kwargs.get("especialidades", []),
                "sedes": kwargs.get("sedes", []),
            },
        }
        return self.client.post(API, json=body)

    def _aceptar(self, id_vinculacion: int, id_usuario: int):
        self._as_user(id_usuario)
        return self.client.post(f"{API}/{id_vinculacion}/aceptar")

    def _detalle(self, id_vinculacion: int, id_usuario: int = 1):
        self._as_user(id_usuario)
        return self.client.get(f"{API}/{id_vinculacion}")

    def _link(self, id_vinculacion: int) -> VinculacionMedicoEntidad:
        with self.SessionLocal() as db:
            return db.get(VinculacionMedicoEntidad, id_vinculacion)

    # --------------------------------------------------------------- pruebas
    def test_busqueda_global_exacta_autorizada_y_minimizada(self):
        self._as_user(1)
        respuesta = self.client.get(
            f"{API}/candidatos",
            params={"criterio": "correo", "valor": "MEDICO2@test.com"},
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.text)
        data = respuesta.json()
        self.assertEqual(data["id_usuario"], 4)
        self.assertEqual(data["matricula_profesional"], "MAT-B")
        self.assertTrue(data["existe_perfil"])
        self.assertNotIn("password_hash", data)
        self.assertNotIn("roles", data)
        self.assertNotIn("vinculaciones", data)
        self.assertTrue(data["documento_identidad"].startswith("****"))
        self.assertNotEqual(data["documento_identidad"], "2222222 CB")

        por_matricula = self.client.get(
            f"{API}/candidatos",
            params={"criterio": "matricula_profesional", "valor": "mat-b"},
        )
        self.assertEqual(por_matricula.status_code, 200, por_matricula.text)
        self.assertEqual(por_matricula.json()["id_usuario"], 4)

        inexistente = self.client.get(
            f"{API}/candidatos",
            params={"criterio": "correo", "valor": "nadie@test.com"},
        )
        self.assertEqual(inexistente.status_code, 404)

    def test_busqueda_rechaza_no_admin_y_superadmin(self):
        self._as_user(3)
        self.assertEqual(
            self.client.get(
                f"{API}/candidatos",
                params={"criterio": "correo", "valor": "medico2@test.com"},
            ).status_code,
            403,
        )

        self._as_user(5)
        self.assertEqual(
            self.client.get(
                f"{API}/candidatos",
                params={"criterio": "correo", "valor": "medico2@test.com"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                f"{API}/candidatos",
                params={"criterio": "correo", "valor": "medico2@test.com"},
                headers={"X-Tenant-ID": "1"},
            ).status_code,
            403,
        )

        # Cuenta con rol ADMIN global pero sin clínica: tampoco administra.
        self._as_user(6)
        self.assertEqual(
            self.client.get(
                f"{API}/candidatos",
                params={"criterio": "correo", "valor": "medico2@test.com"},
            ).status_code,
            403,
        )

    def test_entidad_administrada_sale_del_usuario_no_del_header(self):
        # El admin de la entidad 1 no puede redirigir la creación con el header.
        self._as_user(1)
        respuesta = self.client.post(
            API,
            headers={"X-Tenant-ID": "2"},
            json={
                "modo": "EXISTENTE",
                "id_usuario": 7,
                "asignaciones": {
                    "roles": [2],
                    "id_rol_principal": 2,
                    "especialidades": [],
                    "sedes": [],
                },
            },
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.text)
        id_link = respuesta.json()["vinculacion"]["id_vinculacion"]
        self.assertEqual(self._link(id_link).id_clinica, 1)

    def test_crear_cuenta_nueva_genera_credencial_temporal(self):
        respuesta = self._crear_nuevo()
        self.assertEqual(respuesta.status_code, 201, respuesta.text)
        data = respuesta.json()
        self.assertTrue(data["perfil_pendiente"])
        self.assertIsNone(data["vinculacion"]["id_medico"])
        self.assertEqual(data["vinculacion"]["estado"], "INVITADO")
        credencial = data["credencial_temporal"]
        self.assertEqual(credencial["correo"], "nuevo@test.com")
        self.assertTrue(credencial["password_temporal"])

        with self.SessionLocal() as db:
            usuario = db.scalar(
                select(Usuario).where(Usuario.correo == "nuevo@test.com")
            )
            self.assertIsNotNone(usuario)
            self.assertIsNone(usuario.id_clinica)
            self.assertIsNone(usuario.id_rol)
            self.assertNotEqual(usuario.password_hash, credencial["password_temporal"])
            fila = db.scalar(
                select(CredencialTemporalMedico).where(
                    CredencialTemporalMedico.id_usuario == usuario.id_usuario
                )
            )
            self.assertIsNotNone(fila)
            self.assertIsNone(fila.usada_en)
            expira = fila.expira_en
            if expira.tzinfo is not None:
                expira = expira.astimezone(timezone.utc).replace(tzinfo=None)
            self.assertGreater(expira, datetime.now(timezone.utc).replace(tzinfo=None))

        duplicado_correo = self._crear_nuevo(documento="8888888 LP")
        self.assertEqual(duplicado_correo.status_code, 409)

        duplicado_doc = self._crear_nuevo(
            correo="otro@test.com", documento="9999999 LP"
        )
        self.assertEqual(duplicado_doc.status_code, 409)

    def test_crear_rechaza_cuenta_no_elegible_y_payload_invalido(self):
        inelegible = self._crear_existente(8, expected=422)
        self.assertIn("no tiene perfil", inelegible.text)

        self._as_user(1)
        con_tenant = self.client.post(
            API,
            json={
                "modo": "EXISTENTE",
                "id_usuario": 7,
                "id_clinica": 1,
                "asignaciones": {
                    "roles": [2],
                    "id_rol_principal": 2,
                    "especialidades": [],
                    "sedes": [],
                },
            },
        )
        self.assertEqual(con_tenant.status_code, 422)

        principal_ajeno = self._crear_existente(
            7, roles=[2], principal=6, expected=422
        )
        self.assertEqual(principal_ajeno.status_code, 422)

        rol_otra_entidad = self._crear_existente(
            7, roles=[7], principal=7, expected=422
        )
        self.assertIn("otra entidad", rol_otra_entidad.text)

        especialidad_inactiva = self._crear_existente(
            7,
            especialidades=[{"id_especialidad": 3, "es_principal": True}],
            expected=422,
        )
        self.assertIn("inactiva", especialidad_inactiva.text)

        sede_inexistente = self._crear_existente(7, sedes=[99], expected=422)
        self.assertIn("no existen", sede_inexistente.text)

        sede_otra_entidad = self._crear_existente(7, sedes=[2], expected=422)
        self.assertIn("otra entidad", sede_otra_entidad.text)

        sede_inactiva = self._crear_existente(7, sedes=[3], expected=422)
        self.assertIn("inactiva", sede_inactiva.text)

        # Rol principal duplicado en especialidades.
        dos_principales = self._crear_existente(
            7,
            especialidades=[
                {"id_especialidad": 1, "es_principal": True},
                {"id_especialidad": 2, "es_principal": True},
            ],
            expected=422,
        )
        self.assertEqual(dos_principales.status_code, 422)

    def test_duplicado_de_vinculacion_y_aislamiento_entre_entidades(self):
        primera = self._crear_existente(7)
        repetida = self._crear_existente(7, expected=409)
        self.assertIn("Ya existe", repetida.text)

        id_link = primera.json()["vinculacion"]["id_vinculacion"]
        self._as_user(2)
        ajeno = self.client.get(f"{API}/{id_link}")
        self.assertEqual(ajeno.status_code, 404)
        self.assertNotIn("medico", ajeno.text.lower())
        self._as_user(2)
        self.assertEqual(self.client.get(API).json()["total"], 0)
        self._as_user(1)
        self.assertEqual(self.client.get(API).json()["total"], 1)

    def test_aceptar_rechazar_invitacion_propia(self):
        creada = self._crear_existente(7)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]

        ajeno = self._aceptar(id_link, 3)
        self.assertEqual(ajeno.status_code, 403)

        aceptada = self._aceptar(id_link, 7)
        self.assertEqual(aceptada.status_code, 200, aceptada.text)
        self.assertEqual(aceptada.json()["estado"], "ACTIVO")
        self.assertEqual(aceptada.json()["row_version"], 2)

        repetida = self._aceptar(id_link, 7)
        self.assertEqual(repetida.status_code, 409)

        otra = self._crear_existente(7, expected=409)
        self.assertEqual(otra.status_code, 409)

        # Rechazo en otra entidad para el mismo médico global.
        self._as_user(2)
        creada_dos = self.client.post(
            API,
            json={
                "modo": "EXISTENTE",
                "id_usuario": 7,
                "asignaciones": {
                    "roles": [2],
                    "id_rol_principal": 2,
                    "especialidades": [],
                    "sedes": [],
                },
            },
        )
        self.assertEqual(creada_dos.status_code, 201, creada_dos.text)
        id_dos = creada_dos.json()["vinculacion"]["id_vinculacion"]
        self._as_user(7)
        rechazo = self.client.post(
            f"{API}/{id_dos}/rechazar", json={"motivo": "No participaré"}
        )
        self.assertEqual(rechazo.status_code, 200, rechazo.text)
        self.assertEqual(rechazo.json()["estado"], "RECHAZADO")
        self.assertEqual(rechazo.json()["motivo_estado"], "No participaré")
        repetido = self.client.post(
            f"{API}/{id_dos}/rechazar", json={"motivo": "Otra vez"}
        )
        self.assertEqual(repetido.status_code, 409)

    def test_asignaciones_efectivas_roles_multiples_y_version(self):
        creada = self._crear_existente(7)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]

        self._as_user(1)
        reemplazo = self.client.put(
            f"{API}/{id_link}/asignaciones",
            json={
                "roles": [2, 6],
                "id_rol_principal": 2,
                "especialidades": [
                    {"id_especialidad": 1, "es_principal": True},
                    {"id_especialidad": 2, "es_principal": False},
                ],
                "sedes": [],
                "row_version": 1,
            },
        )
        self.assertEqual(reemplazo.status_code, 200, reemplazo.text)
        self.assertEqual(reemplazo.json()["row_version"], 2)
        self.assertEqual(len(reemplazo.json()["roles"]), 2)
        self.assertEqual(
            [r["nombre"] for r in reemplazo.json()["roles"]],
            ["MEDICO", "MEDICO_ESPECIALISTA"],
        )
        self.assertEqual(len(reemplazo.json()["especialidades"]), 2)

        obsoleta = self.client.put(
            f"{API}/{id_link}/asignaciones",
            json={
                "roles": [2],
                "id_rol_principal": 2,
                "especialidades": [],
                "sedes": [],
                "row_version": 1,
            },
        )
        self.assertEqual(obsoleta.status_code, 409)
        detalle = self._detalle(id_link)
        self.assertEqual(len(detalle.json()["vinculacion"]["roles"]), 2)

        with self.SessionLocal() as db:
            principales = db.scalar(
                select(func.count())
                .select_from(VinculacionMedicoRol)
                .where(
                    VinculacionMedicoRol.id_vinculacion == id_link,
                    VinculacionMedicoRol.es_principal.is_(True),
                )
            )
            self.assertEqual(principales, 1)

        # El médico acepta y el contexto deriva permisos de ambos roles.
        self._aceptar(id_link, 7)
        self._as_user(7)
        contexto = self.client.get(
            "/api/v1/tenant/context", headers={"X-Tenant-ID": "1"}
        )
        self.assertEqual(contexto.status_code, 200, contexto.text)
        data = contexto.json()
        self.assertEqual(data["rol"], "MEDICO")
        self.assertEqual(set(data["roles"]), {"MEDICO", "MEDICO_ESPECIALISTA"})
        self.assertIn("medicos:read", data["permisos"])
        self.assertIn("consultas:write", data["permisos"])
        self.assertNotIn("inactivo:test", data["permisos"])

    def test_asignacion_de_sedes_por_vinculo(self):
        creada = self._crear_existente(7, sedes=[1])
        id_link = creada.json()["vinculacion"]["id_vinculacion"]
        detalle = self._detalle(id_link)
        self.assertEqual(detalle.status_code, 200, detalle.text)
        self.assertEqual(detalle.json()["vinculacion"]["sedes"], [1])

        self._as_user(1)
        sin_sedes = self.client.put(
            f"{API}/{id_link}/asignaciones",
            json={
                "roles": [2],
                "id_rol_principal": 2,
                "especialidades": [],
                "sedes": [],
                "row_version": 1,
            },
        )
        self.assertEqual(sin_sedes.status_code, 200, sin_sedes.text)
        self.assertEqual(sin_sedes.json()["sedes"], [])

        con_sedes = self.client.put(
            f"{API}/{id_link}/asignaciones",
            json={
                "roles": [2],
                "id_rol_principal": 2,
                "especialidades": [],
                "sedes": [1],
                "row_version": 2,
            },
        )
        self.assertEqual(con_sedes.status_code, 200, con_sedes.text)
        self.assertEqual(con_sedes.json()["sedes"], [1])
        self.assertEqual(con_sedes.json()["row_version"], 3)

        detalle = self._detalle(id_link)
        asignaciones = [
            evento
            for evento in detalle.json()["historial"]
            if evento["tipo_evento"] == "ASIGNACIONES"
        ]
        self.assertEqual(len(asignaciones), 2)
        self.assertEqual(asignaciones[-1]["datos"]["despues"]["sedes"], [1])
        self.assertEqual(asignaciones[-1]["datos"]["antes"]["sedes"], [])

        with self.SessionLocal() as db:
            filas = db.scalars(
                select(VinculacionMedicoSede).where(
                    VinculacionMedicoSede.id_vinculacion == id_link
                )
            ).all()
            self.assertEqual([fila.id_sede for fila in filas], [1])

    def test_no_se_permite_mas_de_un_rol_principal(self):
        creada = self._crear_existente(7)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]
        with self.SessionLocal() as db:
            db.add_all(
                [
                    VinculacionMedicoRol(
                        id_vinculacion=id_link, id_rol=2, es_principal=True
                    ),
                    VinculacionMedicoRol(
                        id_vinculacion=id_link, id_rol=6, es_principal=True
                    ),
                ]
            )
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_maquina_de_estados_suspender_reactivar_y_baja(self):
        creada = self._crear_existente(7)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]
        self.assertEqual(self._aceptar(id_link, 7).status_code, 200)

        self._as_user(1)
        invalido = self.client.patch(
            f"{API}/{id_link}/estado",
            json={"estado": "INVITADO", "row_version": 2},
        )
        self.assertEqual(invalido.status_code, 422)

        obsoleta = self.client.patch(
            f"{API}/{id_link}/estado",
            json={
                "estado": "SUSPENDIDO",
                "motivo": "Licencia médica",
                "row_version": 1,
            },
        )
        self.assertEqual(obsoleta.status_code, 409)

        suspendida = self.client.patch(
            f"{API}/{id_link}/estado",
            json={
                "estado": "SUSPENDIDO",
                "motivo": "Licencia médica",
                "row_version": 2,
            },
        )
        self.assertEqual(suspendida.status_code, 200, suspendida.text)
        self.assertEqual(suspendida.json()["estado"], "SUSPENDIDO")
        self.assertEqual(suspendida.json()["row_version"], 3)

        # El vínculo suspendido no concede contexto operativo.
        self._as_user(7)
        self.assertEqual(
            self.client.get(
                "/api/v1/tenant/context", headers={"X-Tenant-ID": "1"}
            ).status_code,
            403,
        )

        self._as_user(1)
        reactivada = self.client.patch(
            f"{API}/{id_link}/estado",
            json={"estado": "ACTIVO", "row_version": 3},
        )
        self.assertEqual(reactivada.status_code, 200, reactivada.text)
        self.assertEqual(reactivada.json()["estado"], "ACTIVO")

        baja = self.client.patch(
            f"{API}/{id_link}/estado",
            json={
                "estado": "BAJA",
                "motivo": "Fin de la relación laboral",
                "row_version": 4,
            },
        )
        self.assertEqual(baja.status_code, 200, baja.text)
        self.assertEqual(baja.json()["estado"], "BAJA")

        terminal = self.client.patch(
            f"{API}/{id_link}/estado",
            json={"estado": "ACTIVO", "row_version": 5},
        )
        self.assertEqual(terminal.status_code, 409)

        asignaciones_terminales = self.client.put(
            f"{API}/{id_link}/asignaciones",
            json={
                "roles": [2],
                "id_rol_principal": 2,
                "especialidades": [],
                "sedes": [],
                "row_version": 5,
            },
        )
        self.assertEqual(asignaciones_terminales.status_code, 409)

    def test_guardas_operativas_deniegan_vinculo_suspendido(self):
        creada = self._crear_existente(7, roles=[2], principal=2)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]
        self.assertEqual(self._aceptar(id_link, 7).status_code, 200)

        # Un vínculo sin perfil sigue bloqueando operaciones clínicas; para
        # verificar suspensión/reactivación se completa primero el onboarding.
        with self.SessionLocal() as db:
            medico = Medico(
                id_usuario=7,
                id_clinica=1,
                matricula_profesional="MAT-GLOBAL",
                estado="activo",
            )
            db.add(medico)
            db.flush()
            vinculo = db.get(VinculacionMedicoEntidad, id_link)
            vinculo.id_medico = medico.id_medico
            db.commit()

        self._as_user(1)
        self.assertEqual(
            self.client.patch(
                f"{API}/{id_link}/estado",
                json={
                    "estado": "SUSPENDIDO",
                    "motivo": "Prueba de guardas",
                    "row_version": 2,
                },
            ).status_code,
            200,
        )

        self._as_user(7)
        for ruta in (
            "/citas",
            "/appointments/agenda/servicios",
            "/medicos",
            "/api/v1/recetas",
            "/api/v1/medicamentos",
        ):
            respuesta = self.client.get(ruta, headers={"X-Tenant-ID": "1"})
            self.assertEqual(respuesta.status_code, 403, f"{ruta}: {respuesta.text}")

        self._as_user(1)
        reactivada = self.client.patch(
            f"{API}/{id_link}/estado",
            json={"estado": "ACTIVO", "row_version": 3},
        )
        self.assertEqual(reactivada.status_code, 200, reactivada.text)

        self._as_user(7)
        for ruta in (
            "/citas",
            "/appointments/agenda/servicios",
            "/medicos",
        ):
            respuesta = self.client.get(ruta, headers={"X-Tenant-ID": "1"})
            self.assertEqual(respuesta.status_code, 200, f"{ruta}: {respuesta.text}")

    def test_dos_entidades_mismo_medico_y_contexto_aislado(self):
        # Entidad 1: rol global + rol especialista local.
        primera = self._crear_existente(
            7,
            roles=[2, 6],
            principal=2,
            especialidades=[{"id_especialidad": 1, "es_principal": True}],
        )
        id_uno = primera.json()["vinculacion"]["id_vinculacion"]
        self._aceptar(id_uno, 7)

        # Entidad 2: solo rol local de la entidad 2.
        self._as_user(2)
        segunda = self.client.post(
            API,
            json={
                "modo": "EXISTENTE",
                "id_usuario": 7,
                "asignaciones": {
                    "roles": [7],
                    "id_rol_principal": 7,
                    "especialidades": [],
                    "sedes": [],
                },
            },
        )
        self.assertEqual(segunda.status_code, 201, segunda.text)
        id_dos = segunda.json()["vinculacion"]["id_vinculacion"]
        self._aceptar(id_dos, 7)

        self._as_user(7)
        contexto_uno = self.client.get(
            "/api/v1/tenant/context", headers={"X-Tenant-ID": "1"}
        )
        self.assertEqual(contexto_uno.status_code, 200, contexto_uno.text)
        self.assertEqual(contexto_uno.json()["clinica_id"], 1)
        self.assertEqual(
            set(contexto_uno.json()["roles"]),
            {"MEDICO", "MEDICO_ESPECIALISTA"},
        )
        self.assertIn("medicos:read", contexto_uno.json()["permisos"])

        contexto_dos = self.client.get(
            "/api/v1/tenant/context", headers={"X-Tenant-ID": "2"}
        )
        self.assertEqual(contexto_dos.status_code, 200, contexto_dos.text)
        self.assertEqual(contexto_dos.json()["clinica_id"], 2)
        self.assertEqual(contexto_dos.json()["roles"], ["MEDICO"])
        self.assertIn("recetas:read", contexto_dos.json()["permisos"])
        self.assertNotIn("consultas:write", contexto_dos.json()["permisos"])

        ajeno = self.client.get(
            "/api/v1/tenant/context", headers={"X-Tenant-ID": "99"}
        )
        self.assertEqual(ajeno.status_code, 403)

        mias = self.client.get(f"{API}/mias")
        self.assertEqual(mias.status_code, 200, mias.text)
        self.assertEqual(mias.json()["total"], 2)

        entidades = self.client.get(f"{API}/mias/entidades")
        self.assertEqual(entidades.status_code, 200, entidades.text)
        self.assertEqual(
            entidades.json(),
            {
                "items": [
                    {"id_clinica": 1, "nombre": "Clínica Uno"},
                    {"id_clinica": 2, "nombre": "Clínica Dos"},
                ]
            },
        )

        # Un admin de la entidad 1 no ve el vínculo de la entidad 2.
        self._as_user(1)
        self.assertEqual(self.client.get(f"{API}/{id_dos}").status_code, 404)

    def test_historial_clinico_sobrevive_a_la_baja_del_vinculo(self):
        creada = self._crear_existente(3)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]
        self.assertEqual(self._aceptar(id_link, 3).status_code, 200)

        with self.SessionLocal() as db:
            db.add(
                Cita(
                    id_cita=100,
                    id_clinica=1,
                    id_paciente=1,
                    id_medico=1,
                    id_especialidad=1,
                    fecha_cita=date(2026, 11, 20),
                    estado="COMPLETADA",
                    fecha_creacion=datetime.now(timezone.utc),
                )
            )
            db.commit()

        self._as_user(1)
        baja = self.client.patch(
            f"{API}/{id_link}/estado",
            json={
                "estado": "BAJA",
                "motivo": "Desvinculación administrativa",
                "row_version": 2,
            },
        )
        self.assertEqual(baja.status_code, 200, baja.text)

        with self.SessionLocal() as db:
            self.assertIsNotNone(db.get(Cita, 100))
            self.assertIsNotNone(db.get(Medico, 1))

    def test_auditoria_fallida_revierte_la_creacion_completa(self):
        with patch(
            "app.modules.appointments.doctor_entity_links.service."
            "registrar_auditoria_async",
            side_effect=RuntimeError("fallo de auditoría"),
        ):
            respuesta = self._crear_nuevo(correo="rollback@test.com")
        self.assertEqual(respuesta.status_code, 500)

        with self.SessionLocal() as db:
            self.assertIsNone(
                db.scalar(
                    select(Usuario).where(Usuario.correo == "rollback@test.com")
                )
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(VinculacionMedicoEntidad)
                ),
                0,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(
                        CredencialTemporalMedico
                    )
                ),
                0,
            )

    def test_auditoria_fallida_revierte_asignaciones(self):
        creada = self._crear_existente(7)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]
        with patch(
            "app.modules.appointments.doctor_entity_links.service."
            "registrar_auditoria_async",
            side_effect=RuntimeError("fallo de auditoría"),
        ):
            self._as_user(1)
            respuesta = self.client.put(
                f"{API}/{id_link}/asignaciones",
                json={
                    "roles": [6],
                    "id_rol_principal": 6,
                    "especialidades": [],
                    "sedes": [],
                    "row_version": 1,
                },
            )
        self.assertEqual(respuesta.status_code, 500)

        with self.SessionLocal() as db:
            roles = db.scalars(
                select(VinculacionMedicoRol).where(
                    VinculacionMedicoRol.id_vinculacion == id_link
                )
            ).all()
            self.assertEqual([r.id_rol for r in roles], [2])
            self.assertEqual(db.get(VinculacionMedicoEntidad, id_link).row_version, 1)

    def test_historial_y_auditoria_en_la_misma_transaccion(self):
        creada = self._crear_existente(7)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]
        detalle = self._detalle(id_link)
        self.assertEqual(detalle.status_code, 200, detalle.text)
        historial = detalle.json()["historial"]
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["tipo_evento"], "CREACION")
        self.assertEqual(historial[0]["estado_nuevo"], "INVITADO")

        with self.SessionLocal() as db:
            auditorias = db.scalars(
                select(Auditoria).where(
                    Auditoria.tabla_afectada == "vinculaciones_medico_entidad",
                    Auditoria.registro_id == id_link,
                )
            ).all()
            self.assertEqual(len(auditorias), 1)
            self.assertEqual(auditorias[0].accion, "CREAR_VINCULACION_MEDICO")

    def test_credencial_temporal_un_solo_uso_y_cambio_obligatorio(self):
        creada = self._crear_nuevo(correo="temp@test.com", documento="7777777 LP")
        self.assertEqual(creada.status_code, 201, creada.text)
        password_temporal = creada.json()["credencial_temporal"]["password_temporal"]

        with self.SessionLocal() as db:
            usuario = db.scalar(
                select(Usuario).where(Usuario.correo == "temp@test.com")
            )
            id_usuario = usuario.id_usuario
            autenticado = authenticate_user(db, "temp@test.com", password_temporal)
            self.assertIsNotNone(autenticado)
            self.assertTrue(user_must_change_password(db, id_usuario))
            credencial = db.scalar(
                select(CredencialTemporalMedico).where(
                    CredencialTemporalMedico.id_usuario == id_usuario
                )
            )
            self.assertIsNotNone(credencial.usada_en)

            # El primer login invalida el hash temporal.
            self.assertIsNone(
                authenticate_user(db, "temp@test.com", password_temporal)
            )

        self._as_password_change_user(id_usuario)
        cambio = self.client.post(
            "/api/v1/auth/change-temporary-password",
            json={
                "nueva_password": "Definitiva123!",
                "confirmar_password": "Definitiva123!",
            },
        )
        self.assertEqual(cambio.status_code, 200, cambio.text)

        with self.SessionLocal() as db:
            self.assertFalse(user_must_change_password(db, id_usuario))
            self.assertIsNotNone(
                authenticate_user(db, "temp@test.com", "Definitiva123!")
            )
            self.assertIsNone(
                authenticate_user(db, "temp@test.com", password_temporal)
            )

    def test_rutas_canonicas_y_alias_legacy(self):
        paths = app.openapi()["paths"]
        for ruta in (
            "/api/v1/medicos/vinculaciones",
            "/api/v1/medicos/vinculaciones/candidatos",
            "/api/v1/medicos/vinculaciones/mias",
            "/api/v1/medicos/vinculaciones/mias/entidades",
            "/api/v1/medicos/vinculaciones/{id_vinculacion}",
            "/api/v1/medicos/vinculaciones/{id_vinculacion}/aceptar",
            "/api/v1/medicos/vinculaciones/{id_vinculacion}/rechazar",
            "/api/v1/medicos/vinculaciones/{id_vinculacion}/asignaciones",
            "/api/v1/medicos/vinculaciones/{id_vinculacion}/estado",
            "/api/v1/auth/login",
            "/api/v1/auth/change-temporary-password",
            "/auth/login",
            "/medicos/vinculaciones",
            "/medicos",
            "/appointments/medicos",
            "/tenant/context",
            "/api/v1/tenant/context",
            "/appointments/agenda/servicios",
            "/appointments/consultas",
            "/citas",
            "/appointments/citas",
            "/cola",
            "/api/v1/cola",
            "/api/v1/recetas",
            "/api/v1/medicamentos",
        ):
            self.assertIn(ruta, paths)

        # El alias legacy responde con el mismo contrato.
        creada = self._crear_existente(7)
        id_link = creada.json()["vinculacion"]["id_vinculacion"]
        self._as_user(1)
        legacy = self.client.get(f"{LEGACY}/{id_link}")
        self.assertEqual(legacy.status_code, 200, legacy.text)

    def test_matricula_global_unica_en_orm(self):
        with self.SessionLocal() as db:
            db.add(
                Medico(
                    id_medico=99,
                    id_usuario=7,
                    id_clinica=1,
                    matricula_profesional="MAT-B",
                    estado="activo",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()


class CU29MigrationHelpersTestCase(unittest.TestCase):
    """Ejercita los helpers reales de la migración 025."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        from pathlib import Path

        ruta = (
            Path(__file__).resolve().parents[1]
            / "alembic"
            / "versions"
            / "025_cu29_vincular_medico_entidad.py"
        )
        spec = importlib.util.spec_from_file_location("cu29_migration", ruta)
        cls.migracion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.migracion)

    def test_aborta_por_matriculas_duplicadas_cross_entity(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE medicos (id_medico INTEGER PRIMARY KEY, "
                    "id_clinica INTEGER, matricula_profesional TEXT)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO medicos VALUES (1, 1, 'DUP-1'), (2, 2, 'DUP-1')"
                )
            )
            with self.assertRaises(RuntimeError) as error:
                self.migracion._abortar_si_matriculas_duplicadas(conn)
            self.assertIn("DUP-1", str(error.exception))
        engine.dispose()

    def test_backfill_idempotente_conserva_columnas_legacy(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        fabrica = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        with fabrica() as db:
            db.add_all(
                [
                    Clinica(id_clinica=1, nombre="Uno", estado="ACTIVO"),
                    Rol(id_rol=2, id_clinica=None, nombre="MEDICO", estado="ACTIVO"),
                    Usuario(
                        id_usuario=10,
                        id_clinica=1,
                        id_rol=2,
                        nombres="Back",
                        apellidos="Fill",
                        correo="backfill@test.com",
                        password_hash="hash",
                        estado="activo",
                    ),
                    Especialidad(
                        id_especialidad=1, nombre="General", estado="activo"
                    ),
                    Medico(
                        id_medico=10,
                        id_usuario=10,
                        id_clinica=1,
                        matricula_profesional="BACK-1",
                        estado="activo",
                    ),
                    MedicoEspecialidad(
                        id_medico=10, id_especialidad=1, es_principal=True
                    ),
                ]
            )
            db.commit()

        with engine.begin() as conn:
            self.migracion._backfill_vinculaciones(conn)
            self.migracion._backfill_vinculaciones(conn)
            vinculos = conn.execute(
                text("SELECT estado, id_clinica, id_usuario, id_medico FROM vinculaciones_medico_entidad")
            ).fetchall()
            self.assertEqual(vinculos, [("ACTIVO", 1, 10, 10)])
            roles = conn.execute(
                text("SELECT id_rol, es_principal FROM vinculacion_medico_rol")
            ).fetchall()
            self.assertEqual([(r[0], bool(r[1])) for r in roles], [(2, True)])
            especialidades = conn.execute(
                text("SELECT id_especialidad, es_principal FROM vinculacion_medico_especialidad")
            ).fetchall()
            self.assertEqual(
                [(e[0], bool(e[1])) for e in especialidades], [(1, True)]
            )
            legacy = conn.execute(
                text(
                    "SELECT u.id_clinica, u.id_rol, m.id_clinica "
                    "FROM usuarios u JOIN medicos m ON m.id_usuario=u.id_usuario "
                    "WHERE u.id_usuario=10"
                )
            ).one()
            self.assertEqual(tuple(legacy), (1, 2, 1))
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
