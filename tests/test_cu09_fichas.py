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
from app.modules.appointments.models import Cita, Especialidad, Medico, MedicoEspecialidad, ServicioMedico
from app.modules.medical_records.models import FichaClinica, Paciente


class CU09FichasTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False, expire_on_commit=False)
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
            conn.exec_driver_sql("DELETE FROM fichas_clinicas")
            conn.exec_driver_sql("DELETE FROM citas")
            conn.exec_driver_sql("DELETE FROM medico_especialidad")
            conn.exec_driver_sql("DELETE FROM especialidades")
            conn.exec_driver_sql("DELETE FROM medicos")
            conn.exec_driver_sql("DELETE FROM servicios_medicos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

    def _seed_data(self):
        db = self.SessionLocal()
        try:
            # 1. Clinicas
            clinica1 = Clinica(id_clinica=1, nombre="Clínica Santa Cruz")
            clinica2 = Clinica(id_clinica=2, nombre="Hospital Central")
            db.add_all([clinica1, clinica2])

            # 2. Roles
            rol_admin = Rol(id_rol=1, id_clinica=1, nombre="Administrador", estado="ACTIVO")
            rol_medico = Rol(id_rol=2, id_clinica=1, nombre="Médico", estado="ACTIVO")
            rol_paciente = Rol(id_rol=4, id_clinica=1, nombre="Paciente", estado="ACTIVO")
            db.add_all([rol_admin, rol_medico, rol_paciente])

            # 3. Usuarios
            self.user_admin = Usuario(
                id_usuario=1, id_clinica=1, id_rol=1,
                nombres="Admin", apellidos="SaaS", correo="admin@santacruz.com",
                password_hash="hash", estado="ACTIVO"
            )
            self.user_medico = Usuario(
                id_usuario=2, id_clinica=1, id_rol=2,
                nombres="Carlos", apellidos="Ramos", correo="carlos.ramos@santacruz.com",
                password_hash="hash", estado="ACTIVO"
            )
            self.user_paciente = Usuario(
                id_usuario=3, id_clinica=1, id_rol=4,
                nombres="Juan", apellidos="Perez", correo="juan.perez@test.com",
                password_hash="hash", estado="ACTIVO"
            )
            self.user_tenant2 = Usuario(
                id_usuario=4, id_clinica=2, id_rol=1,
                nombres="Admin2", apellidos="Central", correo="admin@central.com",
                password_hash="hash", estado="ACTIVO"
            )
            db.add_all([self.user_admin, self.user_medico, self.user_paciente, self.user_tenant2])
            db.flush()

            # 4. Especialidad & Servicio
            especialidad = Especialidad(id_especialidad=1, nombre="Cardiología", estado="activo")
            db.add(especialidad)
            db.flush()

            from datetime import time
            servicio = ServicioMedico(
                id_servicio=1, nombre="Consulta Externa Cardiología",
                hora_inicio=time(8, 0), hora_fin=time(14, 0), duracion_minutos=30, costo=150.0, estado="activo"
            )
            db.add(servicio)
            db.flush()

            # 5. Medico
            medico = Medico(
                id_medico=1, id_usuario=2, matricula_profesional="MED-9988", estado="activo"
            )
            db.add(medico)
            db.flush()

            med_esp = MedicoEspecialidad(id_medico=1, id_especialidad=1, es_principal=True)
            db.add(med_esp)

            # 6. Paciente
            paciente = Paciente(
                id_paciente=1, id_clinica=1, id_usuario=3,
                nombres="Juan", apellidos="Perez", ci="9988776", complemento="",
                fecha_nacimiento=date(1988, 5, 20),
                genero="M", telefono="71122334", estado="ACTIVO"
            )
            db.add(paciente)

            db.commit()
        finally:
            db.close()

    def test_emitir_ficha_exitosa_y_correlativo_unico(self):
        payload1 = {
            "id_paciente": 1,
            "id_medico": 1,
            "id_especialidad": 1,
            "id_servicio": 1,
            "fecha_atencion": "2026-09-10",
            "hora_inicio": "09:00",
            "hora_fin": "09:30",
            "motivo_consulta": "Dolor precordial opresivo",
            "signos_vitales": {
                "presion_arterial": "130/80",
                "frecuencia_cardiaca": 82
            },
            "secciones_dinamicas": {
                "tipo_plantilla": "CARDIOLOGIA"
            }
        }
        res1 = self.client.post("/medical-records/fichas", json=payload1, headers={"X-Tenant-ID": "1"})
        self.assertEqual(res1.status_code, 201, res1.text)
        data1 = res1.json()
        self.assertTrue(data1["correlativo"].startswith("FICH-20260910-"))
        self.assertEqual(data1["correlativo"], "FICH-20260910-0001")
        self.assertEqual(data1["estado"], "EMITIDA")
        self.assertEqual(data1["id_paciente"], 1)
        self.assertEqual(data1["id_medico"], 1)

        # Emisión de segunda ficha en horario posterior: correlativo consecutivo 0002
        payload2 = dict(payload1)
        payload2["hora_inicio"] = "09:30"
        payload2["hora_fin"] = "10:00"
        res2 = self.client.post("/fichas", json=payload2, headers={"X-Tenant-ID": "1"})
        self.assertEqual(res2.status_code, 201, res2.text)
        data2 = res2.json()
        self.assertEqual(data2["correlativo"], "FICH-20260910-0002")

    def test_concurrencia_colision_turno_409(self):
        payload = {
            "id_paciente": 1,
            "id_medico": 1,
            "id_especialidad": 1,
            "fecha_atencion": "2026-09-10",
            "hora_inicio": "10:00",
            "hora_fin": "10:30",
            "motivo_consulta": "Control rutinario"
        }
        # Primera emisión exitosa
        res1 = self.client.post("/medical-records/fichas", json=payload, headers={"X-Tenant-ID": "1"})
        self.assertEqual(res1.status_code, 201)

        # Intento de sobreposición o doble reserva para el mismo médico y slot: 409 Conflict
        res2 = self.client.post("/medical-records/fichas", json=payload, headers={"X-Tenant-ID": "1"})
        self.assertEqual(res2.status_code, 409)
        self.assertIn("ocupado", res2.json()["detail"].lower())

    def test_listar_fichas_con_filtros(self):
        # Crear 2 fichas
        for hora in ["11:00", "11:30"]:
            p = {
                "id_paciente": 1,
                "id_medico": 1,
                "fecha_atencion": "2026-09-11",
                "hora_inicio": hora,
                "hora_fin": "12:00",
                "motivo_consulta": f"Chequeo {hora}"
            }
            self.client.post("/medical-records/fichas", json=p, headers={"X-Tenant-ID": "1"})

        # Listar sin filtros
        res = self.client.get("/medical-records/fichas", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertGreaterEqual(body["total"], 2)

        # Filtrar por fecha
        res_fecha = self.client.get("/fichas?fecha=2026-09-11", headers={"X-Tenant-ID": "1"})
        self.assertEqual(res_fecha.status_code, 200)
        self.assertEqual(res_fecha.json()["total"], 2)

    def test_detalle_ficha_y_secciones_dinamicas(self):
        p = {
            "id_paciente": 1,
            "id_medico": 1,
            "fecha_atencion": "2026-09-12",
            "hora_inicio": "08:30",
            "hora_fin": "09:00",
            "motivo_consulta": "Consulta pediátrica",
            "signos_vitales": {"peso_kg": 14.5, "temperatura": 37.1},
            "secciones_dinamicas": {
                "tipo_plantilla": "PEDIATRIA",
                "percentil_peso": "P50",
                "vacunas_completas": True
            }
        }
        create_res = self.client.post("/medical-records/fichas", json=p, headers={"X-Tenant-ID": "1"})
        id_ficha = create_res.json()["id_ficha"]

        detail_res = self.client.get(f"/medical-records/fichas/{id_ficha}", headers={"X-Tenant-ID": "1"})
        self.assertEqual(detail_res.status_code, 200)
        ficha = detail_res.json()
        self.assertEqual(ficha["signos_vitales"]["peso_kg"], 14.5)
        self.assertEqual(ficha["secciones_dinamicas"]["tipo_plantilla"], "PEDIATRIA")
        self.assertTrue(ficha["secciones_dinamicas"]["vacunas_completas"])

    def test_actualizacion_clinica_medica_cie10(self):
        p = {
            "id_paciente": 1,
            "id_medico": 1,
            "fecha_atencion": "2026-09-13",
            "hora_inicio": "14:00",
            "hora_fin": "14:30",
            "motivo_consulta": "Sospecha de hipertensión"
        }
        create_res = self.client.post("/medical-records/fichas", json=p, headers={"X-Tenant-ID": "1"})
        id_ficha = create_res.json()["id_ficha"]

        update_payload = {
            "signos_vitales": {"presion_arterial": "140/90", "frecuencia_cardiaca": 88},
            "secciones_dinamicas": {"auscultacion": "Ruidos rítmicos sin soplos"},
            "codigo_cie10": "I10",
            "diagnostico_descripcion": "Hipertensión esencial (primaria)",
            "notas_evolucion": "Se inicia tratamiento antihipertensivo con Enalapril 10mg diario.",
            "estado": "FINALIZADA"
        }
        patch_res = self.client.patch(f"/medical-records/fichas/{id_ficha}/clinica", json=update_payload, headers={"X-Tenant-ID": "1"})
        self.assertEqual(patch_res.status_code, 200)
        data = patch_res.json()
        self.assertEqual(data["estado"], "FINALIZADA")
        self.assertEqual(data["codigo_cie10"], "I10")
        self.assertEqual(data["diagnostico_descripcion"], "Hipertensión esencial (primaria)")
        self.assertIn("Enalapril", data["notas_evolucion"])

    def test_cancelar_ficha_y_prohibicion_post_finalizada(self):
        # 1. Cancelar ficha EMITIDA
        p = {
            "id_paciente": 1,
            "id_medico": 1,
            "fecha_atencion": "2026-09-14",
            "hora_inicio": "15:00",
            "hora_fin": "15:30",
            "motivo_consulta": "Chequeo para cancelar"
        }
        create_res = self.client.post("/medical-records/fichas", json=p, headers={"X-Tenant-ID": "1"})
        id_ficha = create_res.json()["id_ficha"]

        cancel_res = self.client.post(
            f"/medical-records/fichas/{id_ficha}/cancelar",
            json={"motivo_cancelacion": "Paciente no asistió por viaje"},
            headers={"X-Tenant-ID": "1"}
        )
        self.assertEqual(cancel_res.status_code, 200)
        self.assertEqual(cancel_res.json()["estado"], "CANCELADA")

        # 2. Intentar cancelar ficha FINALIZADA -> 400 Bad Request
        p2 = {
            "id_paciente": 1,
            "id_medico": 1,
            "fecha_atencion": "2026-09-14",
            "hora_inicio": "16:00",
            "hora_fin": "16:30",
            "motivo_consulta": "Chequeo para finalizar"
        }
        create_res2 = self.client.post("/medical-records/fichas", json=p2, headers={"X-Tenant-ID": "1"})
        id_ficha2 = create_res2.json()["id_ficha"]
        self.client.patch(
            f"/medical-records/fichas/{id_ficha2}/clinica",
            json={"estado": "FINALIZADA", "notas_evolucion": "Atención concluida"},
            headers={"X-Tenant-ID": "1"}
        )

        cancel_res2 = self.client.post(
            f"/medical-records/fichas/{id_ficha2}/cancelar",
            json={"motivo_cancelacion": "Intento de cancelación no permitida"},
            headers={"X-Tenant-ID": "1"}
        )
        self.assertEqual(cancel_res2.status_code, 400)

    def test_aislamiento_multitenant(self):
        # Crear ficha en tenant 1
        p = {
            "id_paciente": 1,
            "id_medico": 1,
            "fecha_atencion": "2026-09-15",
            "hora_inicio": "17:00",
            "hora_fin": "17:30",
            "motivo_consulta": "Ficha confidencial clínica 1"
        }
        create_res = self.client.post("/medical-records/fichas", json=p, headers={"X-Tenant-ID": "1"})
        id_ficha = create_res.json()["id_ficha"]

        # Cambiar contexto a usuario de clínica 2
        self._mock_user(self.user_tenant2)

        # Intentar acceder a ficha de clínica 1 desde clínica 2: debe responder 404 Not Found
        res_cross = self.client.get(f"/medical-records/fichas/{id_ficha}", headers={"X-Tenant-ID": "2"})
        self.assertEqual(res_cross.status_code, 404)


if __name__ == "__main__":
    unittest.main()
