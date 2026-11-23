"""CU07 Lista de espera y reasignacion de turnos (sqlite + overrides, patron CU08)."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.modules.appointments.consultas.schemas import CitaUpdate
from app.modules.appointments.consultas.service import actualizar_cita
from app.modules.appointments.lista_espera import service as waitlist_service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario

PREFIX = "/api/v1/lista-espera"


class CU07ListaEsperaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
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
            """CREATE TABLE servicios_medicos (id_servicio INTEGER PRIMARY KEY, id_clinica INTEGER,
                tenant_id TEXT, nombre TEXT NOT NULL, descripcion TEXT,
                modalidad TEXT NOT NULL DEFAULT 'PRESENCIAL', hora_inicio TIME NOT NULL, hora_fin TIME NOT NULL,
                duracion_minutos INTEGER NOT NULL, costo DECIMAL(10,2) NOT NULL, estado TEXT NOT NULL)""",
            """CREATE TABLE bloqueos_agenda (id_bloqueo INTEGER PRIMARY KEY, id_medico INTEGER NOT NULL,
                id_servicio INTEGER NOT NULL, fecha DATE NOT NULL, hora_inicio TIME NOT NULL,
                hora_fin TIME NOT NULL, motivo TEXT NOT NULL, estado TEXT NOT NULL)""",
            """CREATE TABLE notificaciones (id_notificacion INTEGER PRIMARY KEY, id_clinica INTEGER,
                id_usuario INTEGER NOT NULL, outbox_id INTEGER, rol_destinatario TEXT,
                tipo TEXT, categoria TEXT DEFAULT 'SISTEMA', canal TEXT, canal_badge TEXT,
                titulo TEXT, mensaje TEXT, recurso_tipo TEXT, recurso_id TEXT, enlace_accion TEXT,
                payload_extra TEXT, fecha_programada TIMESTAMP,
                fecha_envio TIMESTAMP, fecha_lectura TIMESTAMP, estado TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
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
            """CREATE TABLE lista_espera (id_lista_espera INTEGER PRIMARY KEY, id_clinica INTEGER NOT NULL,
                id_paciente INTEGER NOT NULL, id_medico INTEGER, id_especialidad INTEGER, fecha_deseada DATE,
                estado TEXT NOT NULL DEFAULT 'EN_ESPERA', prioridad INTEGER NOT NULL DEFAULT 0, motivo TEXT,
                id_cita_ofrecida INTEGER, fecha_ofrecimiento TIMESTAMP, fecha_respuesta TIMESTAMP,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP)""",
        ]
        with cls.engine.begin() as conn:
            for statement in statements:
                conn.exec_driver_sql(statement)

    def setUp(self):
        self._push = patch.object(waitlist_service, "enviar_push_usuario", return_value=0)
        self._push.start()
        with self.engine.begin() as conn:
            for name in (
                "notificaciones", "lista_espera", "citas", "pacientes", "bloqueos_agenda",
                "servicios_medicos", "medico_especialidad", "especialidades", "medicos",
                "usuarios", "roles", "clinicas",
            ):
                conn.exec_driver_sql(f"DELETE FROM {name}")
            conn.exec_driver_sql("INSERT INTO clinicas VALUES (1, 'Central'), (2, 'Otra')")
            conn.exec_driver_sql("""INSERT INTO roles (id_rol,nombre,estado) VALUES
                (1,'Administración','ACTIVO'), (2,'Médico','ACTIVO'),
                (3,'Recepción','ACTIVO'), (4,'Paciente','ACTIVO')""")
            for uid, clinic, role in ((1, 1, 1), (2, 1, 2), (3, 1, 3), (4, 1, 4),
                                      (5, 2, 2), (6, 1, 4), (7, 1, 4), (9, 2, 4)):
                conn.execute(text("""INSERT INTO usuarios (id_usuario,id_clinica,id_rol,nombres,apellidos,correo,password_hash,estado)
                    VALUES (:id,:clinic,:role,'Nombre','Apellido',:email,'hash','ACTIVO')"""),
                    {"id": uid, "clinic": clinic, "role": role, "email": f"u{uid}@test.local"})
            conn.exec_driver_sql("""INSERT INTO medicos (id_medico,id_usuario,id_clinica,matricula_profesional,estado)
                VALUES (20,2,1,'M20','activo'), (50,5,2,'M50','activo')""")
            conn.exec_driver_sql("INSERT INTO especialidades VALUES (10,'Cardiología','x','ACTIVA')")
            conn.exec_driver_sql("INSERT INTO medico_especialidad VALUES (20,10,1)")
            conn.exec_driver_sql("""INSERT INTO servicios_medicos
                (id_servicio,id_clinica,nombre,descripcion,hora_inicio,hora_fin,duracion_minutos,costo,estado) VALUES
                (1,1,'Consulta general',NULL,'08:00:00','13:00:00',20,100,'activo')""")
            conn.exec_driver_sql("""INSERT INTO pacientes
                (id_paciente,id_clinica,id_usuario,nombres,apellidos,ci,fecha_nacimiento,genero,telefono,estado)
                VALUES (40,1,4,'Mateo','Valdez','8472910','1992-05-14','M','+5911','ACTIVO'),
                       (41,1,6,'Ana','Perez','2222222','1998-01-01','F','+5912','ACTIVO'),
                       (43,1,7,'Luis','Paz','3333333','2000-06-06','M','+5913','ACTIVO'),
                       (90,2,9,'Otro','Paciente','9999999','1990-01-01','M','+5919','ACTIVO')""")
            conn.exec_driver_sql("""INSERT INTO citas
                (id_cita,id_clinica,id_paciente,id_medico,id_especialidad,id_servicio,fecha_cita,
                 hora_inicio,hora_fin,estado,tipo_consulta)
                VALUES (101,1,41,20,10,1,'2026-12-01','09:00','09:20','CONFIRMADA','PRESENCIAL')""")
        self._as(4)

    def tearDown(self):
        self._push.stop()
        app.dependency_overrides.pop(get_current_user, None)

    def _as(self, user_id):
        def dependency():
            with self.SessionLocal() as db:
                user = db.get(Usuario, user_id)
                _ = user.rol
                return user
        app.dependency_overrides[get_current_user] = dependency

    def _inscribir(self, **extra):
        payload = {"id_medico": 20, "id_especialidad": 10, "fecha_deseada": "2026-12-01", **extra}
        return self.client.post(PREFIX, json=payload)

    def _notificaciones(self):
        with self.SessionLocal() as db:
            return db.execute(text("SELECT id_usuario,tipo,estado FROM notificaciones")).all()

    def _citas(self):
        with self.SessionLocal() as db:
            return db.execute(text("SELECT id_cita,id_paciente,estado,hora_inicio FROM citas ORDER BY id_cita")).all()

    # --- Inscripcion -------------------------------------------------------
    def test_paciente_se_inscribe_y_ve_posicion(self):
        response = self._inscribir(motivo="Sin cupos")
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data["estado"], "EN_ESPERA")
        self.assertEqual(data["posicion"], 1)
        self.assertEqual(data["id_paciente"], 40)
        self.assertEqual(data["prioridad"], 0)

        mias = self.client.get(PREFIX + "/mi-espera")
        self.assertEqual(mias.status_code, 200, mias.text)
        self.assertEqual(len(mias.json()), 1)
        self.assertEqual(mias.json()[0]["id_lista_espera"], data["id_lista_espera"])

    def test_inscripcion_duplicada_devuelve_409(self):
        self.assertEqual(self._inscribir().status_code, 201)
        self.assertEqual(self._inscribir().status_code, 409)

    def test_prioridad_del_paciente_se_ignora(self):
        data = self._inscribir(prioridad=5).json()
        self.assertEqual(data["prioridad"], 0)

    def test_staff_inscribe_con_prioridad(self):
        self._as(3)
        response = self.client.post(PREFIX, json={
            "id_paciente": 41, "id_medico": 20, "id_especialidad": 10, "prioridad": 3,
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["prioridad"], 3)

    # --- Posicion ----------------------------------------------------------
    def test_posicion_por_prioridad_y_antiguedad(self):
        self._as(3)
        self.client.post(PREFIX, json={"id_paciente": 41, "id_medico": 20, "id_especialidad": 10})
        self.client.post(PREFIX, json={"id_paciente": 43, "id_medico": 20, "id_especialidad": 10, "prioridad": 2})

        self._as(6)
        ana = self.client.get(PREFIX + "/mi-espera").json()[0]
        self.assertEqual(ana["posicion"], 2)

        self._as(7)
        luis = self.client.get(PREFIX + "/mi-espera").json()[0]
        self.assertEqual(luis["posicion"], 1)

    # --- Salida ------------------------------------------------------------
    def test_salir_de_la_lista(self):
        entrada = self._inscribir().json()
        response = self.client.delete(f"{PREFIX}/{entrada['id_lista_espera']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["estado"], "CANCELADO")
        self.assertEqual(self.client.get(PREFIX + "/mi-espera").json()[0]["posicion"], 0)

    # --- Reasignacion por cancelacion -------------------------------------
    def test_cancelacion_reasigna_y_notifica(self):
        entrada = self._inscribir().json()
        with self.SessionLocal() as db:
            actualizar_cita(db, 101, CitaUpdate(estado="CANCELADA"))

        with self.SessionLocal() as db:
            estado = db.execute(text(
                "SELECT estado,id_cita_ofrecida FROM lista_espera WHERE id_lista_espera=:id"
            ), {"id": entrada["id_lista_espera"]}).one()
            self.assertEqual(estado.estado, "OFRECIDO")
            self.assertIsNotNone(estado.id_cita_ofrecida)
            nueva = db.execute(text(
                "SELECT estado,fecha_cita,hora_inicio FROM citas WHERE id_cita=:id"
            ), {"id": estado.id_cita_ofrecida}).one()
            self.assertEqual(nueva.estado, "PENDIENTE")
            self.assertEqual(str(nueva.fecha_cita), "2026-12-01")
            self.assertEqual(nueva.hora_inicio, "09:00")

        avisos = self._notificaciones()
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0].id_usuario, 4)
        self.assertEqual(avisos[0].tipo, "TURNO_REASIGNADO")

    def test_cancelacion_sin_candidatos_no_crea_cita(self):
        with self.SessionLocal() as db:
            actualizar_cita(db, 101, CitaUpdate(estado="CANCELADA"))
        self.assertEqual(len(self._citas()), 1)
        self.assertEqual(self._notificaciones(), [])

    # --- Confirmar / rechazar ---------------------------------------------
    def test_confirmar_turno_ofrecido(self):
        entrada = self._inscribir().json()
        with self.SessionLocal() as db:
            actualizar_cita(db, 101, CitaUpdate(estado="CANCELADA"))

        response = self.client.post(f"{PREFIX}/{entrada['id_lista_espera']}/confirmar")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["estado"], "CONFIRMADO")

        with self.SessionLocal() as db:
            cita = db.execute(text(
                "SELECT estado FROM citas WHERE id_cita=:id"
            ), {"id": response.json()["id_cita_ofrecida"]}).one()
            self.assertEqual(cita.estado, "CONFIRMADA")

    def test_rechazar_ofrece_al_siguiente(self):
        self._as(3)
        primera = self.client.post(PREFIX, json={
            "id_paciente": 41, "id_medico": 20, "id_especialidad": 10,
        }).json()
        segunda = self.client.post(PREFIX, json={
            "id_paciente": 43, "id_medico": 20, "id_especialidad": 10,
        }).json()

        with self.SessionLocal() as db:
            actualizar_cita(db, 101, CitaUpdate(estado="CANCELADA"))

        self._as(3)
        response = self.client.post(f"{PREFIX}/{primera['id_lista_espera']}/rechazar")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["estado"], "RECHAZADO")

        with self.SessionLocal() as db:
            siguiente = db.execute(text(
                "SELECT estado,id_cita_ofrecida FROM lista_espera WHERE id_lista_espera=:id"
            ), {"id": segunda["id_lista_espera"]}).one()
            self.assertEqual(siguiente.estado, "OFRECIDO")
            self.assertIsNotNone(siguiente.id_cita_ofrecida)

    # --- Liberacion de bloqueo --------------------------------------------
    def test_liberacion_de_bloqueo_ofrece_el_cupo(self):
        entrada = self._inscribir(fecha_deseada="2026-12-02").json()
        bloqueo = SimpleNamespace(
            id_medico=20, id_servicio=1, fecha=date(2026, 12, 2),
            hora_inicio="10:00", hora_fin="10:30",
        )
        with self.SessionLocal() as db:
            waitlist_service.reasignar_por_bloqueo(db, bloqueo)

        with self.SessionLocal() as db:
            estado = db.execute(text(
                "SELECT estado,id_cita_ofrecida FROM lista_espera WHERE id_lista_espera=:id"
            ), {"id": entrada["id_lista_espera"]}).one()
            self.assertEqual(estado.estado, "OFRECIDO")
            nueva = db.execute(text(
                "SELECT fecha_cita,hora_inicio,estado FROM citas WHERE id_cita=:id"
            ), {"id": estado.id_cita_ofrecida}).one()
            self.assertEqual(str(nueva.fecha_cita), "2026-12-02")
            self.assertEqual(nueva.hora_inicio, "10:00")
            self.assertEqual(nueva.estado, "PENDIENTE")

    # --- Seguridad ---------------------------------------------------------
    def test_paciente_no_ve_inscripcion_ajena(self):
        entrada = self._inscribir().json()
        self._as(6)  # Ana tiene otro paciente (41), no el 40
        self.assertEqual(self.client.delete(f"{PREFIX}/{entrada['id_lista_espera']}").status_code, 404)

    def test_staff_de_otra_clinica_no_ve_la_inscripcion(self):
        entrada = self._inscribir().json()
        self._as(5)  # Medico de la clinica 2
        self.assertEqual(self.client.delete(f"{PREFIX}/{entrada['id_lista_espera']}").status_code, 404)
        self.assertEqual(self.client.get(PREFIX).json()["total"], 0)

    def test_listado_staff_filtra_por_estado(self):
        self._inscribir()
        self._as(3)
        data = self.client.get(PREFIX, params={"estado": "EN_ESPERA"}).json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["paciente_nombre"], "Mateo Valdez")
        self.assertEqual(self.client.get(PREFIX, params={"estado": "CONFIRMADO"}).json()["total"], 0)

    def test_confirmar_sin_oferta_devuelve_409(self):
        entrada = self._inscribir().json()
        self.assertEqual(self.client.post(f"{PREFIX}/{entrada['id_lista_espera']}/confirmar").status_code, 409)


if __name__ == "__main__":
    unittest.main()
