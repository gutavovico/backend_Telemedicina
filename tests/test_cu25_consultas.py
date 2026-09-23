import unittest
from datetime import date, datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.appointments.models import Especialidad, Medico, MedicoEspecialidad, Cita
from app.modules.medical_records.models import Paciente


class CU25ConsultasTestCase(unittest.TestCase):
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
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        self._reset_data()
        self._seed_data()
        self._mock_user(self.user_admin)

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _mock_user(self, user: Usuario):
        app.dependency_overrides[get_current_user] = lambda: user

    def _reset_data(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM citas")
            conn.exec_driver_sql("DELETE FROM medico_especialidad")
            conn.exec_driver_sql("DELETE FROM especialidades")
            conn.exec_driver_sql("DELETE FROM medicos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

    def _seed_data(self):
        db = self.SessionLocal()
        try:
            # 1. Clinica
            clinica = Clinica(id_clinica=1, nombre="Clínica San Juan")
            db.add(clinica)

            # 2. Roles
            rol_admin = Rol(id_rol=1, id_clinica=1, nombre="Administrador", estado="ACTIVO")
            rol_medico = Rol(id_rol=2, id_clinica=1, nombre="Médico", estado="ACTIVO")
            rol_paciente = Rol(id_rol=4, id_clinica=1, nombre="Paciente", estado="ACTIVO")
            db.add_all([rol_admin, rol_medico, rol_paciente])

            # 3. Usuarios
            self.user_admin = Usuario(
                id_usuario=1, id_clinica=1, id_rol=1,
                nombres="Admin", apellidos="Hospital", correo="admin@hospital.com",
                password_hash="hash", estado="ACTIVO"
            )
            user_medico = Usuario(
                id_usuario=2, id_clinica=1, id_rol=2,
                nombres="Carlos", apellidos="Mendoza", correo="carlos.mendoza@hospital.com",
                password_hash="hash", estado="ACTIVO"
            )
            user_paciente = Usuario(
                id_usuario=3, id_clinica=1, id_rol=4,
                nombres="Ana", apellidos="Gomez", correo="ana.gomez@test.com",
                password_hash="hash", estado="ACTIVO"
            )
            db.add_all([self.user_admin, user_medico, user_paciente])
            db.flush()

            # 4. Especialidad
            especialidad = Especialidad(
                id_especialidad=1, nombre="Cardiología", estado="activo"
            )
            db.add(especialidad)
            db.flush()

            # 5. Medico
            medico = Medico(
                id_medico=1, id_usuario=2, matricula_profesional="MED-1234",
                estado="activo"
            )
            db.add(medico)
            db.flush()

            med_esp = MedicoEspecialidad(id_medico=1, id_especialidad=1, es_principal=True)
            db.add(med_esp)

            # 6. Paciente
            paciente = Paciente(
                id_paciente=1, id_clinica=1, id_usuario=3,
                nombres="Ana", apellidos="Gomez", ci="8877665", complemento="1A",
                fecha_nacimiento=date(1990, 1, 1),
                genero="F", telefono="70011223", estado="activo"
            )
            db.add(paciente)

            db.commit()
        finally:
            db.close()

    def test_agendar_cita_exitoso_y_duplicado(self):
        payload = {
            "id_paciente": 1,
            "id_medico": 1,
            "id_especialidad": 1,
            "fecha_cita": "2026-09-15",
            "hora_inicio": "09:00",
            "hora_fin": "09:30",
            "motivo": "Control cardiológico",
            "estado": "PENDIENTE",
            "tipo_consulta": "TELEMEDICINA",
            "notas": "Primera consulta virtual"
        }
        # Agendar cita exitosa
        resp = self.client.post("/appointments/consultas", json=payload)
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()
        self.assertIn("id_cita", data)
        self.assertEqual(data["paciente_nombre"], "Ana Gomez")
        self.assertEqual(data["paciente_ci"], "ID: 8877665-1A")
        self.assertEqual(data["paciente_iniciales"], "AG")
        self.assertEqual(data["medico_nombre"], "Dr(a). Carlos Mendoza")
        self.assertEqual(data["especialidad_nombre"], "Cardiología")
        self.assertEqual(data["estado"], "PENDIENTE")

        # Intentar agendar en el mismo horario debe fallar (400)
        resp_dup = self.client.post("/appointments/consultas", json=payload)
        self.assertEqual(resp_dup.status_code, 400)
        self.assertIn("ya está ocupado", resp_dup.json()["detail"])

    def test_agendar_cita_paciente_o_medico_inexistente(self):
        payload_bad_pac = {
            "id_paciente": 999,
            "id_medico": 1,
            "fecha_cita": "2026-09-15",
            "hora_inicio": "10:00"
        }
        resp = self.client.post("/appointments/consultas", json=payload_bad_pac)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("El paciente con ID 999 no existe", resp.json()["detail"])

        payload_bad_med = {
            "id_paciente": 1,
            "id_medico": 999,
            "fecha_cita": "2026-09-15",
            "hora_inicio": "10:00"
        }
        resp = self.client.post("/appointments/consultas", json=payload_bad_med)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("El médico con ID 999 no existe", resp.json()["detail"])

    def test_listar_citas_con_filtros_y_busqueda(self):
        # Crear 2 citas
        self.client.post("/appointments/consultas", json={
            "id_paciente": 1, "id_medico": 1, "id_especialidad": 1,
            "fecha_cita": "2026-09-15", "hora_inicio": "08:00",
            "motivo": "Chequeo rutinario", "estado": "CONFIRMADA"
        })
        self.client.post("/appointments/consultas", json={
            "id_paciente": 1, "id_medico": 1, "id_especialidad": 1,
            "fecha_cita": "2026-09-16", "hora_inicio": "10:00",
            "motivo": "Dolor torácico", "estado": "PENDIENTE"
        })

        # Listar todas
        resp = self.client.get("/appointments/consultas")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 2)

        # Buscar por texto q
        resp_q = self.client.get("/appointments/consultas?q=torácico")
        self.assertEqual(resp_q.status_code, 200)
        self.assertEqual(resp_q.json()["total"], 1)
        self.assertEqual(resp_q.json()["items"][0]["motivo"], "Dolor torácico")

        # Filtrar por fecha
        resp_fecha = self.client.get("/appointments/consultas?fecha=2026-09-15")
        self.assertEqual(resp_fecha.status_code, 200)
        self.assertEqual(resp_fecha.json()["total"], 1)

        # Filtrar por estado
        resp_estado = self.client.get("/appointments/consultas?estado=CONFIRMADA")
        self.assertEqual(resp_estado.status_code, 200)
        self.assertEqual(resp_estado.json()["total"], 1)

    def test_obtener_y_actualizar_cita(self):
        crear_resp = self.client.post("/appointments/consultas", json={
            "id_paciente": 1, "id_medico": 1, "id_especialidad": 1,
            "fecha_cita": "2026-09-20", "hora_inicio": "11:00",
            "motivo": "Consulta inicial"
        })
        id_cita = crear_resp.json()["id_cita"]

        # Obtener detalle
        resp_get = self.client.get(f"/appointments/consultas/{id_cita}")
        self.assertEqual(resp_get.status_code, 200)
        self.assertEqual(resp_get.json()["id_cita"], id_cita)

        # Actualizar cita
        resp_put = self.client.put(f"/appointments/consultas/{id_cita}", json={
            "estado": "CONFIRMADA",
            "hora_inicio": "11:30",
            "motivo": "Consulta confirmada y reprogramada"
        })
        self.assertEqual(resp_put.status_code, 200)
        self.assertEqual(resp_put.json()["estado"], "CONFIRMADA")
        self.assertEqual(resp_put.json()["hora_inicio"], "11:30")

    def test_horarios_disponibles(self):
        # Agendar cita a las 09:30
        self.client.post("/appointments/consultas", json={
            "id_paciente": 1, "id_medico": 1,
            "fecha_cita": "2026-09-22", "hora_inicio": "09:30"
        })

        resp = self.client.get("/appointments/consultas/horarios-disponibles?id_medico=1&fecha=2026-09-22")
        self.assertEqual(resp.status_code, 200)
        slots = resp.json()
        self.assertGreater(len(slots), 0)

        slot_930 = next((s for s in slots if s["hora"] == "09:30"), None)
        self.assertIsNotNone(slot_930)
        self.assertFalse(slot_930["disponible"])

        slot_1000 = next((s for s in slots if s["hora"] == "10:00"), None)
        self.assertIsNotNone(slot_1000)
        self.assertTrue(slot_1000["disponible"])

    def test_eliminar_cita(self):
        crear_resp = self.client.post("/appointments/consultas", json={
            "id_paciente": 1, "id_medico": 1,
            "fecha_cita": "2026-09-25", "hora_inicio": "14:00"
        })
        id_cita = crear_resp.json()["id_cita"]

        # Eliminar
        resp_del = self.client.delete(f"/appointments/consultas/{id_cita}")
        self.assertEqual(resp_del.status_code, 200)

        # Verificar que ya no existe
        resp_get = self.client.get(f"/appointments/consultas/{id_cita}")
        self.assertEqual(resp_get.status_code, 404)

    def test_compatibilidad_ruta_citas(self):
        # Probar que el prefijo alternativo /citas responde igualmente
        resp = self.client.get("/citas")
        self.assertEqual(resp.status_code, 200)
