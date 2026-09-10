"""Pruebas funcionales SQLite; no sustituyen la exclusión GiST de Neon."""
import unittest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


PREFIX = "/appointments/agenda"


class CU05MedicalAgendaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        cls._create_schema()
        cls.previous_overrides = app.dependency_overrides.copy()

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
        cls.client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(cls.previous_overrides)
        cls.engine.dispose()

    @classmethod
    def _create_schema(cls):
        # DDL explícito como CU02/CU26; tipos de identidad adaptados a SQLite.
        statements = [
            "CREATE TABLE clinicas (id_clinica INTEGER PRIMARY KEY, nombre TEXT)",
            """CREATE TABLE roles (id_rol INTEGER PRIMARY KEY, id_clinica INTEGER,
                nombre TEXT, descripcion TEXT, estado TEXT, fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE usuarios (id_usuario INTEGER PRIMARY KEY, id_clinica INTEGER, id_rol INTEGER,
                nombres TEXT, apellidos TEXT, correo TEXT UNIQUE, telefono TEXT, password_hash TEXT,
                token_version INTEGER DEFAULT 0, foto_perfil TEXT, estado TEXT,
                notificaciones_push BOOLEAN DEFAULT 1, notificaciones_email BOOLEAN DEFAULT 1,
                notificaciones_sms BOOLEAN DEFAULT 0, fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE medicos (id_medico INTEGER PRIMARY KEY, id_usuario INTEGER UNIQUE,
                matricula_profesional TEXT UNIQUE, descripcion_profesional TEXT, experiencia TEXT,
                foto_perfil TEXT, estado TEXT, fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            "CREATE TABLE especialidades (id_especialidad INTEGER PRIMARY KEY, nombre TEXT, descripcion TEXT, estado TEXT)",
            "CREATE TABLE medico_especialidad (id_medico INTEGER, id_especialidad INTEGER, es_principal BOOLEAN)",
            """CREATE TABLE servicios_medicos (id_servicio INTEGER PRIMARY KEY, nombre TEXT NOT NULL,
                descripcion TEXT, hora_inicio TIME NOT NULL, hora_fin TIME NOT NULL,
                duracion_minutos INTEGER NOT NULL, costo DECIMAL(10,2) NOT NULL, estado TEXT NOT NULL)""",
            """CREATE TABLE horarios_medicos (id_horario INTEGER PRIMARY KEY, id_medico INTEGER NOT NULL,
                id_servicio INTEGER NOT NULL, dia_semana INTEGER NOT NULL, estado TEXT NOT NULL,
                UNIQUE(id_medico, id_servicio, dia_semana))""",
            """CREATE TABLE bloqueos_agenda (id_bloqueo INTEGER PRIMARY KEY, id_medico INTEGER NOT NULL,
                id_servicio INTEGER NOT NULL, fecha DATE NOT NULL, hora_inicio TIME NOT NULL,
                hora_fin TIME NOT NULL, motivo TEXT NOT NULL, estado TEXT NOT NULL)""",
            """CREATE TABLE auditoria (id_auditoria INTEGER PRIMARY KEY, id_clinica INTEGER NOT NULL,
                id_usuario INTEGER NOT NULL, tabla_afectada TEXT, registro_id INTEGER, accion TEXT NOT NULL,
                descripcion TEXT, datos_anteriores TEXT, datos_nuevos TEXT, direccion_ip TEXT,
                fecha_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE notificaciones (id_notificacion INTEGER PRIMARY KEY, id_usuario INTEGER NOT NULL,
                tipo TEXT, canal TEXT, titulo TEXT, mensaje TEXT, fecha_programada TIMESTAMP,
                fecha_envio TIMESTAMP, fecha_lectura TIMESTAMP, estado TEXT NOT NULL)""",
            "CREATE TABLE pacientes (id_paciente INTEGER PRIMARY KEY, id_usuario INTEGER, id_clinica INTEGER)",
            """CREATE TABLE citas (id_cita INTEGER PRIMARY KEY, id_paciente INTEGER, id_medico INTEGER,
                id_especialidad INTEGER, fecha_cita DATE, hora_inicio TIME, hora_fin TIME,
                motivo TEXT, estado TEXT, tipo_consulta TEXT, notas TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        ]
        with cls.engine.begin() as conn:
            for statement in statements:
                conn.exec_driver_sql(statement)

    def setUp(self):
        self.clock = patch("app.modules.appointments.agenda.service.hoy_agenda", return_value=date(2026, 9, 9))
        self.clock.start()
        with self.engine.begin() as conn:
            for name in ("notificaciones", "auditoria", "citas", "pacientes", "bloqueos_agenda", "horarios_medicos",
                         "servicios_medicos", "medico_especialidad", "especialidades", "medicos", "usuarios", "roles", "clinicas"):
                conn.exec_driver_sql(f"DELETE FROM {name}")
            conn.exec_driver_sql("INSERT INTO clinicas VALUES (1, 'Central'), (2, 'Otra')")
            conn.exec_driver_sql("""INSERT INTO roles (id_rol,nombre,estado) VALUES
                (1,'Administración','ACTIVO'), (2,'Médico','ACTIVO'), (3,'Recepción','ACTIVO'), (4,'Paciente','ACTIVO')""")
            for uid, clinic, role in ((1,1,1), (2,1,2), (3,1,3), (4,1,4), (5,2,2), (6,1,2), (7,2,1), (8,None,3), (9,2,4)):
                conn.execute(text("""INSERT INTO usuarios (id_usuario,id_clinica,id_rol,nombres,apellidos,correo,password_hash,estado)
                    VALUES (:id,:clinic,:role,'Nombre','Apellido',:email,'hash','activo')"""),
                    {"id":uid,"clinic":clinic,"role":role,"email":f"u{uid}@test.local"})
            conn.exec_driver_sql("""INSERT INTO medicos (id_medico,id_usuario,matricula_profesional,estado)
                VALUES (20,2,'M20','activo'), (50,5,'M50','activo'), (60,6,'M60','activo')""")
            conn.exec_driver_sql("""INSERT INTO servicios_medicos VALUES
                (1,'Consulta general',NULL,'08:00:00','13:00:00',30,100,'activo'),
                (2,'Consulta especializada',NULL,'13:00:00','16:00:00',45,150,'activo'),
                (3,'Evaluación médica',NULL,'16:00:00','18:00:00',60,200,'activo')""")
            conn.exec_driver_sql("INSERT INTO pacientes VALUES (40,4,1), (90,9,2), (41,NULL,1)")
        self._as(2)

    def tearDown(self):
        self.clock.stop()
        app.dependency_overrides.pop(get_current_user, None)

    def _as(self, user_id):
        def dependency():
            with self.SessionLocal() as db:
                user = db.get(Usuario, user_id)
                _ = user.rol
                return user
        app.dependency_overrides[get_current_user] = dependency

    def _horario(self, **changes):
        return self.client.post(PREFIX + "/horarios", json={"id_servicio":1,"dia_semana":4, **changes})

    def _bloqueo(self, **changes):
        return self.client.post(PREFIX + "/bloqueos", json={"id_servicio":1,"fecha":"2026-09-10",
            "hora_inicio":"10:00:00","hora_fin":"11:00:00","motivo":"Ausencia", **changes})

    def _accion(self, id_bloqueo, accion):
        return self.client.patch(f"{PREFIX}/bloqueos/{id_bloqueo}/{accion}")

    def _slots(self):
        response = self.client.get(PREFIX + "/disponibilidad", params={"id_medico":20,"id_servicio":1,"fecha":"2026-09-10"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_servicios_globales_sin_crud(self):
        response = self.client.get(PREFIX + "/servicios")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["id_servicio"] for s in response.json()], [1,2,3])
        self.assertEqual(self.client.post(PREFIX + "/servicios", json={}).status_code, 405)

    def test_crear_horario_propio_y_duplicado(self):
        response = self._horario()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["id_medico"], 20)
        self.assertEqual(self._horario().status_code, 409)

    def test_campos_no_controlables(self):
        for campo in ("hora_inicio", "hora_fin", "duracion_minutos", "modalidad", "tenant_id"):
            with self.subTest(campo=campo):
                self.assertEqual(self._horario(**{campo:"08:00"}).status_code, 422)
        self.assertEqual(self._bloqueo(estado="APROBADO").status_code, 422)
        self.assertEqual(self._bloqueo(motivo="   ").status_code, 422)

    def test_medico_no_puede_suplantar_otro(self):
        self.assertEqual(self._horario(id_medico=60).status_code, 403)
        self.assertEqual(self._bloqueo(id_medico=60).status_code, 403)
        self.assertEqual(self.client.get(PREFIX + "/horarios", params={"id_medico":60}).status_code, 403)

    def test_recepcion_misma_clinica_y_otra_clinica(self):
        self._as(3)
        self.assertEqual(self._horario(id_medico=20).status_code, 201)
        self.assertEqual(self._bloqueo(id_medico=60).status_code, 201)
        self.assertEqual(self._horario(id_medico=50).status_code, 404)
        self.assertEqual(self._bloqueo(id_medico=50).status_code, 404)
        self.assertEqual(self._horario().status_code, 422)

    def test_tenant_header_no_concede_clinica(self):
        self._as(8)
        self.assertEqual(self.client.get(PREFIX + "/horarios", headers={"X-Tenant-ID":"1"}).status_code, 403)

    def test_bloqueo_pendiente_y_regla_manana(self):
        response = self._bloqueo()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["estado"], "PENDIENTE")
        for fecha in ("2026-09-09", "2026-09-11", "2026-02-30"):
            self.assertEqual(self._bloqueo(fecha=fecha).status_code, 422)

    def test_intervalos_invalidos(self):
        for inicio, fin in (("07:30","09:00"), ("12:30","13:30"), ("10:00","10:00"),
                            ("10:00","10:45"), ("10:15","10:45"), ("10:00:01","10:30:01")):
            with self.subTest(inicio=inicio, fin=fin):
                self.assertEqual(self._bloqueo(hora_inicio=inicio,hora_fin=fin).status_code, 422)

    def test_slots_especialidad_y_evaluacion(self):
        self.assertEqual(self._bloqueo(id_servicio=2,hora_inicio="14:30",hora_fin="15:15").status_code, 201)
        self.assertEqual(self._bloqueo(id_servicio=2,hora_inicio="13:30",hora_fin="14:15").status_code, 422)
        self.assertEqual(self._bloqueo(id_servicio=3,hora_inicio="16:00",hora_fin="18:00").status_code, 201)

    def test_solapamiento_y_limites_adyacentes(self):
        self.assertEqual(self._bloqueo().status_code, 201)
        self.assertEqual(self._bloqueo(hora_inicio="10:30",hora_fin="11:30").status_code, 409)
        self.assertEqual(self._bloqueo(hora_inicio="11:00",hora_fin="11:30").status_code, 201)

    def test_aprobar_liberar_y_transiciones(self):
        bid = self._bloqueo().json()["id_bloqueo"]
        self.assertEqual(self._accion(bid,"aprobar").status_code, 403)
        self.assertEqual(self._accion(bid,"liberar").status_code, 409)
        self._as(1)
        self.assertEqual(self._accion(bid,"aprobar").json()["estado"], "APROBADO")
        self.assertEqual(self._accion(bid,"aprobar").status_code, 409)
        self.assertEqual(self._accion(bid,"rechazar").status_code, 409)
        self.assertEqual(self._accion(bid,"liberar").status_code, 403)
        self._as(2)
        self.assertEqual(self._accion(bid,"liberar").json()["estado"], "LIBERADO")
        self.assertEqual(self._accion(bid,"liberar").status_code, 409)
        self.assertEqual(self._bloqueo().status_code, 201)

    def test_rechazar_y_admin_sin_gestion_general(self):
        bid = self._bloqueo().json()["id_bloqueo"]
        self._as(1)
        self.assertEqual(self._accion(bid,"rechazar").json()["estado"], "RECHAZADO")
        self.assertEqual(self._accion(bid,"aprobar").status_code, 409)
        self.assertEqual(self._horario().status_code, 403)
        self.assertEqual(self._bloqueo().status_code, 403)

    def test_listados_y_acciones_aislados(self):
        bid = self._bloqueo().json()["id_bloqueo"]
        hid = self._horario().json()["id_horario"]
        self._as(5)
        self.assertEqual(self.client.get(PREFIX + "/bloqueos").json(), [])
        self.assertEqual(self._accion(bid,"liberar").status_code, 404)
        self.assertEqual(self.client.patch(f"{PREFIX}/horarios/{hid}/estado",json={"estado":"inactivo"}).status_code,404)
        self._as(7)
        self.assertEqual(self.client.get(PREFIX + "/bloqueos").json(), [])
        self.assertEqual(self._accion(bid,"aprobar").status_code, 404)

    def test_disponibilidad_cambia_con_horario_y_bloqueo(self):
        self.assertFalse(any(s["disponible"] for s in self._slots()["slots"]))
        hid = self._horario().json()["id_horario"]
        self.assertEqual(sum(s["disponible"] for s in self._slots()["slots"]), 10)
        bid = self._bloqueo().json()["id_bloqueo"]
        self.assertEqual(sum(s["disponible"] for s in self._slots()["slots"]), 8)
        self._as(1)
        self._accion(bid,"aprobar")
        self._as(2)
        self.assertEqual(sum(s["disponible"] for s in self._slots()["slots"]), 8)
        self._accion(bid,"liberar")
        self.assertEqual(sum(s["disponible"] for s in self._slots()["slots"]), 10)
        self.assertEqual(self.client.patch(f"{PREFIX}/horarios/{hid}/estado",json={"estado":"inactivo"}).status_code,200)
        self.assertFalse(any(s["disponible"] for s in self._slots()["slots"]))
        self.assertEqual(self._horario().status_code,409)
        self.client.patch(f"{PREFIX}/horarios/{hid}/estado",json={"estado":"activo"})
        self.assertEqual(sum(s["disponible"] for s in self._slots()["slots"]), 10)

    def _insert_citas(self):
        with self.engine.begin() as conn:
            for cid, paciente, medico, inicio, fin in ((1,40,20,"09:30:00","10:00:00"),
                    (2,40,20,"10:00:00","10:30:00"), (3,40,20,"10:30:00","11:00:00"),
                    (4,40,20,"11:00:00","11:30:00"), (5,90,50,"10:00:00","10:30:00")):
                conn.execute(text("""INSERT INTO citas (id_cita,id_paciente,id_medico,fecha_cita,hora_inicio,hora_fin,estado)
                    VALUES (:id,:paciente,:medico,'2026-09-10',:inicio,:fin,'ESTADO_REAL_NO_INTERPRETADO')"""),
                    {"id":cid,"paciente":paciente,"medico":medico,"inicio":inicio,"fin":fin})

    def test_citas_afectadas_notificaciones_y_conservacion(self):
        self._insert_citas()
        with self.engine.connect() as conn:
            anteriores = conn.exec_driver_sql("SELECT * FROM citas ORDER BY id_cita").all()
        bid = self._bloqueo().json()["id_bloqueo"]
        self._as(1)
        response = self._accion(bid,"aprobar")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["citas_afectadas"], [2,3])
        self.assertEqual(response.json()["notificaciones_creadas"], 2)
        self.assertEqual(self._accion(bid,"aprobar").status_code,409)
        with self.engine.connect() as conn:
            self.assertEqual(conn.exec_driver_sql("SELECT * FROM citas ORDER BY id_cita").all(), anteriores)
            self.assertEqual(conn.exec_driver_sql("SELECT id_usuario,estado,fecha_envio FROM notificaciones").all(),
                             [(4,"PENDIENTE",None),(4,"PENDIENTE",None)])
            self.assertEqual(conn.exec_driver_sql("SELECT accion FROM auditoria ORDER BY id_auditoria").scalars().all(),
                             ["SOLICITAR","APROBAR"])

    def test_citas_ocupan_disponibilidad_sin_id_servicio(self):
        self._insert_citas()
        self._horario()
        self.assertEqual(sum(s["disponible"] for s in self._slots()["slots"]),6)

    def test_receptor_ausente_o_ajeno_no_se_inventa(self):
        self._insert_citas()
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE citas SET id_paciente=41 WHERE id_cita=2")
            conn.exec_driver_sql("UPDATE citas SET id_paciente=90 WHERE id_cita=3")
        bid = self._bloqueo().json()["id_bloqueo"]
        self._as(1)
        response = self._accion(bid,"aprobar").json()
        self.assertEqual(response["notificaciones_creadas"],0)
        self.assertEqual(len(response["advertencias"]),2)

    def test_falta_citas_se_informa_y_no_declara_slots_libres(self):
        self._horario()
        with self.engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE citas RENAME TO citas_no_disponibles")
        try:
            data = self._slots()
            self.assertFalse(data["citas_verificadas"])
            self.assertTrue(data["advertencias"])
            self.assertFalse(any(s["disponible"] for s in data["slots"]))
            bid = self._bloqueo().json()["id_bloqueo"]
            self._as(1)
            self.assertTrue(self._accion(bid,"aprobar").json()["advertencias"])
        finally:
            with self.engine.begin() as conn:
                conn.exec_driver_sql("ALTER TABLE citas_no_disponibles RENAME TO citas")

    def test_fallo_auditoria_revierte_aprobacion_y_notificaciones(self):
        self._insert_citas()
        bid = self._bloqueo().json()["id_bloqueo"]
        self._as(1)
        with patch("app.modules.appointments.agenda.service._auditar", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                self._accion(bid,"aprobar")
        with self.engine.connect() as conn:
            self.assertEqual(conn.exec_driver_sql("SELECT estado FROM bloqueos_agenda").scalar(), "PENDIENTE")
            self.assertEqual(conn.exec_driver_sql("SELECT COUNT(*) FROM notificaciones").scalar(),0)

    def test_servicio_inactivo_y_no_existente(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE servicios_medicos SET estado='inactivo' WHERE id_servicio=1")
        self.assertEqual(self._bloqueo().status_code,409)
        self.assertEqual(self._horario().status_code,409)
        self.assertEqual(self._horario(id_servicio=999).status_code,404)

    def test_sin_autenticacion_y_rol_paciente(self):
        app.dependency_overrides.pop(get_current_user,None)
        self.assertEqual(self.client.get(PREFIX + "/servicios").status_code,401)
        self._as(4)
        self.assertEqual(self.client.get(PREFIX + "/servicios").status_code,403)

    def test_router_existente_y_diez_endpoints_cu05(self):
        paths = app.openapi()["paths"]
        for path in ("/medicos", "/appointments/medicos", "/especialidades", "/appointments/especialidades"):
            self.assertIn(path, paths)
        agenda = {k:v for k,v in paths.items() if k.startswith(PREFIX)}
        self.assertEqual(sum(len([m for m in methods if m in ("get","post","patch","delete","put")])
                             for methods in agenda.values()),10)
        self.assertEqual(self.client.get("/appointments/especialidades").status_code,200)


if __name__ == "__main__":
    unittest.main()
