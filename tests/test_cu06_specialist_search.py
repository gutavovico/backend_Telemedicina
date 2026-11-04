import unittest
from datetime import date, time
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.appointments.models import (
    BloqueoAgenda,
    Cita,
    Especialidad,
    HorarioMedico,
    Medico,
    MedicoEspecialidad,
    ServicioMedico,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.medical_records.models import Paciente


class CU06SpecialistSearchTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM citas")
            conn.exec_driver_sql("DELETE FROM bloqueos_agenda")
            conn.exec_driver_sql("DELETE FROM horarios_medicos")
            conn.exec_driver_sql("DELETE FROM servicios_medicos")
            conn.exec_driver_sql("DELETE FROM medico_especialidad")
            conn.exec_driver_sql("DELETE FROM especialidades")
            conn.exec_driver_sql("DELETE FROM medicos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

            # 2 tenants (Clínica 1 y Clínica 2)
            conn.exec_driver_sql("INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'Clínica Norte', 'ACTIVO'), (2, 'Clínica Sur', 'ACTIVO')")
            conn.exec_driver_sql("INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES (1, 1, 'PACIENTE', 'activo'), (2, 2, 'PACIENTE', 'activo'), (3, 1, 'MEDICO', 'activo'), (4, 2, 'MEDICO', 'activo')")

            # Usuarios
            # Usuario paciente tenant 1
            conn.exec_driver_sql("""
                INSERT INTO usuarios (id_usuario, id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado, token_version, notificaciones_push, notificaciones_email, notificaciones_sms)
                VALUES (1, 1, 1, 'Paciente', 'Uno', 'paciente1@test.com', 'hash', 'ACTIVO', 0, 1, 1, 0),
                       (2, 2, 2, 'Paciente', 'Dos', 'paciente2@test.com', 'hash', 'ACTIVO', 0, 1, 1, 0),
                       (10, 1, 3, 'Elena', 'Ríos Vargas', 'dra.rios@test.com', 'hash', 'ACTIVO', 0, 1, 1, 0),
                       (11, 1, 3, 'Carlos', 'Gómez', 'dr.gomez@test.com', 'hash', 'ACTIVO', 0, 1, 1, 0),
                       (12, 2, 4, 'Mario', 'Pérez', 'dr.perez@test.com', 'hash', 'ACTIVO', 0, 1, 1, 0)
            """)

            # Paciente record
            conn.exec_driver_sql("""
                INSERT INTO pacientes (id_paciente, id_usuario, id_clinica, nombres, apellidos, ci, fecha_nacimiento, genero, telefono, estado)
                VALUES (1, 1, 1, 'Paciente', 'Uno', '1234567', '1990-01-01', 'M', '77777777', 'ACTIVO'),
                       (2, 2, 2, 'Paciente', 'Dos', '7654321', '1992-02-02', 'F', '78888888', 'ACTIVO')
            """)

            # Médicos: Medico 10 en Clinica 1, Medico 11 en Clinica 1, Medico 12 en Clinica 2
            conn.exec_driver_sql("""
                INSERT INTO medicos (id_medico, id_usuario, id_clinica, matricula_profesional, estado)
                VALUES (10, 10, 1, 'MAT-20381', 'activo'),
                       (11, 11, 1, 'MAT-10101', 'activo'),
                       (12, 12, 2, 'MAT-99999', 'activo')
            """)

            # Especialidades: 1=Cardiología, 2=Pediatría
            conn.exec_driver_sql("INSERT INTO especialidades (id_especialidad, nombre, estado) VALUES (1, 'Cardiología', 'activo'), (2, 'Pediatría', 'activo')")

            # Asignaciones médico-especialidad
            # Dra. Ríos: Cardiología y Pediatría
            conn.exec_driver_sql("INSERT INTO medico_especialidad (id_medico, id_especialidad, es_principal) VALUES (10, 1, 1), (10, 2, 0)")
            # Dr. Gómez: Cardiología
            conn.exec_driver_sql("INSERT INTO medico_especialidad (id_medico, id_especialidad, es_principal) VALUES (11, 1, 1)")
            # Dr. Pérez (Tenant 2): Cardiología
            conn.exec_driver_sql("INSERT INTO medico_especialidad (id_medico, id_especialidad, es_principal) VALUES (12, 1, 1)")

            # Servicios médicos
            # Servicio 1: Teleconsulta Cardiología (Tenant 1), 250 BOB, TELECONSULTA
            # Servicio 2: Presencial Cardiología (Tenant 1), 150 BOB, PRESENCIAL
            # Servicio 3: Teleconsulta Cardiología (Tenant 2), 200 BOB, TELECONSULTA
            conn.exec_driver_sql("""
                INSERT INTO servicios_medicos (id_servicio, id_clinica, nombre, modalidad, costo, duracion_minutos, hora_inicio, hora_fin, estado)
                VALUES (1, 1, 'Teleconsulta cardiológica', 'TELECONSULTA', 250.0, 30, '08:00:00', '12:00:00', 'activo'),
                       (2, 1, 'Consulta cardiológica presencial', 'PRESENCIAL', 150.0, 30, '08:00:00', '12:00:00', 'activo'),
                       (3, 2, 'Teleconsulta ajena', 'TELECONSULTA', 200.0, 30, '08:00:00', '12:00:00', 'activo')
            """)

            # Horarios médicos (para viernes, día de semana 5: por ejemplo 2026-04-10 es viernes)
            # Dra. Ríos (10): Servicio 1 (Teleconsulta) los viernes (dia_semana=5)
            conn.exec_driver_sql("INSERT INTO horarios_medicos (id_horario, id_medico, id_servicio, dia_semana, estado) VALUES (1, 10, 1, 5, 'activo')")
            # Dr. Gómez (11): Servicio 2 (Presencial) los viernes (dia_semana=5)
            conn.exec_driver_sql("INSERT INTO horarios_medicos (id_horario, id_medico, id_servicio, dia_semana, estado) VALUES (2, 11, 2, 5, 'activo')")
            # Dr. Pérez (12): Servicio 3 en tenant 2
            conn.exec_driver_sql("INSERT INTO horarios_medicos (id_horario, id_medico, id_servicio, dia_semana, estado) VALUES (3, 12, 3, 5, 'activo')")

        self.db = self.SessionLocal()
        self.user_paciente1 = self.db.get(Usuario, 1)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_current_user, None)

    def test_busqueda_filtros_combinados_y_aislamiento(self):
        app.dependency_overrides[get_current_user] = lambda: self.user_paciente1

        # Buscar Cardiología, modalidad TELECONSULTA, costo_max 300, fecha 2026-04-10
        resp = self.client.get(
            "/api/v1/especialistas/buscar",
            params={
                "especialidad_id": 1,
                "modalidad": "TELECONSULTA",
                "costo_max": 300,
                "fecha_inicio": "2026-04-10",
                "fecha_fin": "2026-04-10",
            },
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["id_medico"], 10)
        self.assertEqual(item["nombre_completo"], "Elena Ríos Vargas")
        self.assertEqual(len(item["servicios"]), 1)
        self.assertEqual(item["servicios"][0]["modalidad"], "TELECONSULTA")
        self.assertEqual(item["servicios"][0]["costo"], 250.0)

        # No incluye a Carlos Gómez (es PRESENCIAL) ni Mario Pérez (es Tenant 2)
        medicos_ids = [it["id_medico"] for it in data["items"]]
        self.assertNotIn(11, medicos_ids)
        self.assertNotIn(12, medicos_ids)

    def test_rango_fechas_o_costos_invalido_responde_422(self):
        app.dependency_overrides[get_current_user] = lambda: self.user_paciente1

        # costo_min > costo_max
        resp = self.client.get(
            "/api/v1/especialistas/buscar",
            params={
                "costo_min": 500,
                "costo_max": 100,
                "fecha_inicio": "2026-04-10",
                "fecha_fin": "2026-04-10",
            },
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(resp.status_code, 422)

        # fecha_inicio > fecha_fin
        resp2 = self.client.get(
            "/api/v1/especialistas/buscar",
            params={
                "fecha_inicio": "2026-04-15",
                "fecha_fin": "2026-04-10",
            },
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(resp2.status_code, 422)

    def test_disponibilidad_detecta_citas_y_bloqueos(self):
        app.dependency_overrides[get_current_user] = lambda: self.user_paciente1

        # Insertar una cita para la Dra. Ríos el 2026-04-10 de 08:30 a 09:00
        # y un bloqueo de 09:30 a 10:00
        with self.engine.begin() as conn:
            conn.exec_driver_sql("""
                INSERT INTO citas (id_cita, id_clinica, id_paciente, id_medico, fecha_cita, hora_inicio, hora_fin, estado)
                VALUES (101, 1, 1, 10, '2026-04-10', '08:30:00', '09:00:00', 'CONFIRMADA')
            """)
            conn.exec_driver_sql("""
                INSERT INTO bloqueos_agenda (id_bloqueo, id_medico, id_servicio, fecha, hora_inicio, hora_fin, motivo, estado)
                VALUES (201, 10, 1, '2026-04-10', '09:30:00', '10:00:00', 'Congreso médico', 'APROBADO')
            """)

        resp = self.client.get(
            "/api/v1/especialistas/10/disponibilidad",
            params={"fecha_inicio": "2026-04-10", "fecha_fin": "2026-04-10"},
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        slots = data["disponibilidad"][0]["slots"]

        # Slot 08:00 a 08:30 debe estar disponible
        slot_0800 = next(s for s in slots if s["hora_inicio"] == "08:00:00")
        self.assertTrue(slot_0800["disponible"])

        # Slot 08:30 a 09:00 está ocupado por cita
        slot_0830 = next(s for s in slots if s["hora_inicio"] == "08:30:00")
        self.assertFalse(slot_0830["disponible"])

        # Slot 09:00 a 09:30 debe estar disponible
        slot_0900 = next(s for s in slots if s["hora_inicio"] == "09:00:00")
        self.assertTrue(slot_0900["disponible"])

        # Slot 09:30 a 10:00 está ocupado por bloqueo
        slot_0930 = next(s for s in slots if s["hora_inicio"] == "09:30:00")
        self.assertFalse(slot_0930["disponible"])

    def test_bloqueo_pendiente_no_retira_disponibilidad(self):
        app.dependency_overrides[get_current_user] = lambda: self.user_paciente1

        with self.engine.begin() as conn:
            conn.exec_driver_sql("""
                INSERT INTO bloqueos_agenda (id_bloqueo, id_medico, id_servicio, fecha, hora_inicio, hora_fin, motivo, estado)
                VALUES (202, 10, 1, '2026-04-10', '10:00:00', '10:30:00', 'Solicitud sin aprobar', 'PENDIENTE')
            """)

        resp = self.client.get(
            "/api/v1/especialistas/10/disponibilidad",
            params={"fecha_inicio": "2026-04-10", "fecha_fin": "2026-04-10"},
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(resp.status_code, 200)
        slots = resp.json()["disponibilidad"][0]["slots"]
        slot_1000 = next(s for s in slots if s["hora_inicio"] == "10:00:00")
        self.assertTrue(slot_1000["disponible"])

    def test_servicio_sin_clinica_no_se_ofrece(self):
        app.dependency_overrides[get_current_user] = lambda: self.user_paciente1

        with self.engine.begin() as conn:
            conn.exec_driver_sql("""
                INSERT INTO servicios_medicos (id_servicio, id_clinica, nombre, modalidad, costo, duracion_minutos, hora_inicio, hora_fin, estado)
                VALUES (4, NULL, 'Servicio huérfano', 'TELECONSULTA', 100.0, 30, '08:00:00', '12:00:00', 'activo')
            """)
            conn.exec_driver_sql("INSERT INTO horarios_medicos (id_horario, id_medico, id_servicio, dia_semana, estado) VALUES (4, 11, 4, 5, 'activo')")

        resp = self.client.get(
            "/api/v1/especialistas/buscar",
            params={
                "modalidad": "TELECONSULTA",
                "fecha_inicio": "2026-04-10",
                "fecha_fin": "2026-04-10",
            },
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(resp.status_code, 200)
        medicos_ids = [it["id_medico"] for it in resp.json()["items"]]
        self.assertIn(10, medicos_ids)
        self.assertNotIn(11, medicos_ids)

    def test_medico_otro_tenant_retorna_404(self):
        app.dependency_overrides[get_current_user] = lambda: self.user_paciente1

        # Medico 12 pertenece a tenant 2
        resp = self.client.get(
            "/api/v1/especialistas/12/disponibilidad",
            params={"fecha_inicio": "2026-04-10", "fecha_fin": "2026-04-10"},
            headers={"X-Tenant-ID": "1"},
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
