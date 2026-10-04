"""CU08 Live Queue sobre tablas existentes (sqlite + overrides, patrón CU05)."""
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario

PREFIX = "/api/v1/cola"
HOY = date(2026, 10, 4)
AHORA = datetime(2026, 10, 4, 9, 10, tzinfo=timezone(timedelta(hours=-4)))


class CU08LiveQueueTestCase(unittest.TestCase):
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
                id_clinica INTEGER, matricula_profesional TEXT UNIQUE, descripcion_profesional TEXT, experiencia TEXT,
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
            """CREATE TABLE notificaciones (id_notificacion INTEGER PRIMARY KEY, id_usuario INTEGER NOT NULL,
                tipo TEXT, canal TEXT, titulo TEXT, mensaje TEXT, fecha_programada TIMESTAMP,
                fecha_envio TIMESTAMP, fecha_lectura TIMESTAMP, estado TEXT NOT NULL)""",
            """CREATE TABLE pacientes (id_paciente INTEGER PRIMARY KEY, id_clinica INTEGER, id_usuario INTEGER UNIQUE,
                nombres TEXT NOT NULL, apellidos TEXT NOT NULL, ci TEXT NOT NULL, complemento TEXT,
                fecha_nacimiento DATE NOT NULL, genero TEXT NOT NULL, telefono TEXT NOT NULL, correo TEXT,
                direccion TEXT, ciudad TEXT, tipo_sangre TEXT, alergias TEXT, antecedentes_patologicos TEXT,
                contacto_emergencia_nombre TEXT, contacto_emergencia_telefono TEXT,
                contacto_emergencia_parentesco TEXT, seguro_medico TEXT, numero_seguro TEXT,
                estado TEXT NOT NULL, created_at TIMESTAMP, updated_at TIMESTAMP)""",
            """CREATE TABLE citas (id_cita INTEGER PRIMARY KEY, id_clinica INTEGER, id_paciente INTEGER NOT NULL,
                id_medico INTEGER NOT NULL, id_especialidad INTEGER, id_servicio INTEGER, fecha_cita DATE,
                hora_inicio TEXT, hora_fin TEXT, fecha_hora_inicio TIMESTAMP, fecha_hora_fin TIMESTAMP,
                modalidad TEXT, motivo TEXT, estado TEXT, tipo_consulta TEXT, notas TEXT, check_in TIMESTAMP,
                fecha_creacion TIMESTAMP, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        ]
        with cls.engine.begin() as conn:
            for statement in statements:
                conn.exec_driver_sql(statement)

    def setUp(self):
        self._hoy = patch("app.modules.appointments.live_queue.service.hoy_cola", return_value=HOY)
        self._ahora = patch("app.modules.appointments.live_queue.service.ahora_cola", return_value=AHORA)
        self._hoy.start()
        self._ahora.start()
        with self.engine.begin() as conn:
            for name in ("notificaciones", "citas", "pacientes", "bloqueos_agenda", "horarios_medicos",
                          "servicios_medicos", "medico_especialidad", "especialidades", "medicos",
                          "usuarios", "roles", "clinicas"):
                conn.exec_driver_sql(f"DELETE FROM {name}")
            conn.exec_driver_sql("INSERT INTO clinicas VALUES (1, 'Central'), (2, 'Otra')")
            conn.exec_driver_sql("""INSERT INTO roles (id_rol,nombre,estado) VALUES
                (1,'Administración','ACTIVO'), (2,'Médico','ACTIVO'),
                (3,'Recepción','ACTIVO'), (4,'Paciente','ACTIVO')""")
            for uid, clinic, role in ((1, 1, 1), (2, 1, 2), (3, 1, 3), (4, 1, 4),
                                      (5, 2, 2), (6, 1, 4), (7, 1, 4), (9, 2, 4), (10, 1, 4)):
                conn.execute(text("""INSERT INTO usuarios (id_usuario,id_clinica,id_rol,nombres,apellidos,correo,password_hash,estado)
                    VALUES (:id,:clinic,:role,'Nombre','Apellido',:email,'hash','activo')"""),
                    {"id": uid, "clinic": clinic, "role": role, "email": f"u{uid}@test.local"})
            conn.exec_driver_sql("""INSERT INTO medicos (id_medico,id_usuario,id_clinica,matricula_profesional,estado)
                VALUES (20,2,1,'M20','activo'), (50,5,2,'M50','activo')""")
            conn.exec_driver_sql("""INSERT INTO servicios_medicos VALUES
                (1,'Consulta general',NULL,'08:00:00','13:00:00',20,100,'activo')""")
            conn.exec_driver_sql(
                "INSERT INTO horarios_medicos VALUES (1,20,1,6,'activo')")
            conn.exec_driver_sql("""INSERT INTO pacientes
                (id_paciente,id_clinica,id_usuario,nombres,apellidos,ci,fecha_nacimiento,genero,telefono,estado)
                VALUES (40,1,4,'Mateo','Valdez','8472910','1992-05-14','M','+5911','ACTIVO'),
                       (41,1,6,'Ana','Perez','2222222','1998-01-01','F','+5912','ACTIVO'),
                       (43,1,10,'Luis','Paz','3333333','2000-06-06','M','+5913','ACTIVO'),
                       (90,2,9,'Otro','Paciente','9999999','1990-01-01','M','+5919','ACTIVO')""")
            conn.exec_driver_sql("""INSERT INTO citas
                (id_cita,id_clinica,id_paciente,id_medico,fecha_cita,hora_inicio,estado)
                VALUES (101,1,41,20,'2026-10-04','09:00','PENDIENTE'),
                       (102,1,40,20,'2026-10-04','09:20','PENDIENTE'),
                       (103,1,41,20,'2026-10-04','09:40','CONFIRMADA'),
                       (104,2,90,50,'2026-10-04','09:00','PENDIENTE')""")
        self._as(4)

    def tearDown(self):
        self._hoy.stop()
        self._ahora.stop()
        app.dependency_overrides.pop(get_current_user, None)

    def _as(self, user_id):
        def dependency():
            with self.SessionLocal() as db:
                user = db.get(Usuario, user_id)
                _ = user.rol
                return user
        app.dependency_overrides[get_current_user] = dependency

    def _notificaciones(self):
        with self.SessionLocal() as db:
            return db.execute(text("SELECT id_usuario,tipo,estado FROM notificaciones")).all()

    def test_mi_turno_posicion_y_eta_sin_datos_de_terceros(self):
        response = self.client.get(PREFIX + "/mi-turno")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["posicion"], 2)
        self.assertEqual(data["delante"], 1)
        self.assertEqual(data["eta_minutos"], 20)
        self.assertEqual(data["estado"], "PENDIENTE")
        self.assertEqual(data["estado_cola"], "NORMAL")
        self.assertTrue(data["proximo"])
        self.assertNotIn("Ana", response.text)

    def test_mi_turno_sin_cita_hoy(self):
        self._as(10)
        response = self.client.get(PREFIX + "/mi-turno")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["estado_cola"], "SIN_TURNOS")
        self.assertEqual(data["posicion"], 0)

    def test_mi_turno_sin_expediente(self):
        self._as(7)
        self.assertEqual(self.client.get(PREFIX + "/mi-turno").status_code, 404)

    def test_cola_operativa_recepcion(self):
        self._as(3)
        response = self.client.get(PREFIX, params={"id_medico": 20})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["total_pendientes"], 3)
        self.assertEqual([e["hora"] for e in data["entradas"]], ["09:00", "09:20", "09:40"])
        self.assertEqual([e["posicion"] for e in data["entradas"]], [1, 2, 3])
        self.assertNotIn("motivo", response.text)

    def test_avanzar_recalcula_y_notifica(self):
        self._as(3)
        response = self.client.post(f"{PREFIX}/101/avanzar")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        por_id = {e["id_cita"]: e for e in data["entradas"]}
        self.assertEqual(sorted(por_id), [102, 103])
        self.assertEqual(por_id[102]["estado"], "EN_CURSO")
        self.assertEqual(por_id[102]["posicion"], 1)
        avisos = self._notificaciones()
        self.assertEqual(len(avisos), 2)
        self.assertTrue(all(t == "TURNO_PROXIMO" for _, t, _ in avisos))
        self._as(4)
        mateo = self.client.get(PREFIX + "/mi-turno").json()
        self.assertEqual(mateo["posicion"], 1)
        self.assertEqual(mateo["eta_minutos"], 0)
        self._as(3)
        self.assertEqual(self.client.post(f"{PREFIX}/101/avanzar").status_code, 400)

    def test_perdida_reordena(self):
        self._as(2)
        data = self.client.post(f"{PREFIX}/101/perdida").json()
        self.assertEqual([e["id_cita"] for e in data["entradas"]], [102, 103])
        self.assertEqual(data["entradas"][0]["estado"], "EN_CURSO")

    def test_pausa_vigente_pausa_cola_y_suma_eta(self):
        self._as(3)
        pausa = self.client.post(PREFIX + "/pausas", json={
            "id_medico": 20, "fecha": "2026-10-04",
            "hora_inicio": "09:00", "hora_fin": "09:30", "motivo": "Desinfección de consultorio"})
        self.assertEqual(pausa.status_code, 201, pausa.text)
        data = self.client.get(PREFIX, params={"id_medico": 20}).json()
        self.assertEqual(data["estado_cola"], "PAUSADA")
        self.assertIn("09:30", data["mensaje_cola"])
        por_id = {e["id_cita"]: e for e in data["entradas"]}
        self.assertEqual(por_id[102]["eta_minutos"], 40)

    def test_pausa_validaciones(self):
        self._as(3)
        base = {"id_medico": 20, "fecha": "2026-10-04", "hora_inicio": "10:00", "hora_fin": "10:15"}
        self.assertEqual(self.client.post(PREFIX + "/pausas", json={**base, "motivo": "x"}).status_code, 422)
        self.assertEqual(self.client.post(PREFIX + "/pausas", json={**base, "motivo": "Limpieza", "hora_fin": "09:00"}).status_code, 400)
        self.assertEqual(self.client.post(PREFIX + "/pausas", json={**base, "motivo": "Vieja", "fecha": "2026-10-01"}).status_code, 400)

    def test_roles_y_tenant(self):
        self._as(1)
        self.assertEqual(self.client.get(PREFIX, params={"id_medico": 20}).status_code, 403)
        self._as(4)
        self.assertEqual(self.client.get(PREFIX, params={"id_medico": 20}).status_code, 403)
        self._as(3)
        self.assertEqual(self.client.get(PREFIX).status_code, 422)
        self.assertEqual(self.client.get(PREFIX, params={"id_medico": 50}).status_code, 404)
        self._as(2)
        self.assertEqual(self.client.get(PREFIX, params={"id_medico": 50}).status_code, 403)
        self.assertEqual(self.client.post(f"{PREFIX}/104/avanzar").status_code, 404)

    def test_interplay_cu07_reasignacion_aparece_sola(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("""INSERT INTO citas (id_cita,id_clinica,id_paciente,id_medico,fecha_cita,hora_inicio,estado)
                VALUES (105,1,40,20,'2026-10-04','10:00','PENDIENTE')""")
        self._as(3)
        data = self.client.get(PREFIX, params={"id_medico": 20}).json()
        self.assertEqual(data["total_pendientes"], 4)
        self.assertEqual([e["hora"] for e in data["entradas"]], ["09:00", "09:20", "09:40", "10:00"])


if __name__ == "__main__":
    unittest.main()
