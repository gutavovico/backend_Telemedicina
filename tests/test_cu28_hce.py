import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario


class CU28HCETestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(
            bind=cls.engine, autocommit=False, autoflush=False
        )

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

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def _reset_data(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM diagnosticos")
            conn.exec_driver_sql("DELETE FROM consultas")
            conn.exec_driver_sql("DELETE FROM historias_clinicas")
            conn.exec_driver_sql("DELETE FROM citas")
            conn.exec_driver_sql("DELETE FROM medicos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

            # Clínicas (Tenants)
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (1, 'Hospital San Juan de Dios', 'ACTIVO')"
            )
            conn.exec_driver_sql(
                "INSERT INTO clinicas (id_clinica, nombre, estado) VALUES (2, 'Clínica Las Américas', 'ACTIVO')"
            )

            # Roles estándar
            conn.exec_driver_sql(
                """
                INSERT INTO roles (id_rol, id_clinica, nombre, estado) VALUES
                (1, 1, 'ADMIN', 'ACTIVO'),
                (2, 1, 'MEDICO', 'ACTIVO'),
                (3, 1, 'RECEPCION', 'ACTIVO'),
                (4, 1, 'PACIENTE', 'ACTIVO')
                """
            )

            # Usuarios
            conn.exec_driver_sql(
                """
                INSERT INTO usuarios (
                    id_usuario, id_clinica, id_rol, nombres, apellidos, correo,
                    telefono, password_hash, estado, token_version,
                    notificaciones_push, notificaciones_email, notificaciones_sms
                ) VALUES
                (1, 1, 1, 'Admin', 'Sistema', 'admin@test.com', '+59170000000', 'hash1', 'activo', 0, 1, 1, 0),
                (2, 1, 2, 'Medico', 'Uno', 'medico@test.com', '+59170000001', 'hash2', 'activo', 0, 1, 1, 0),
                (3, 1, 3, 'Recepcion', 'Uno', 'recep@test.com', '+59170000002', 'hash3', 'activo', 0, 1, 1, 0),
                (4, 1, 4, 'Paciente', 'Uno', 'paciente@test.com', '+59170000003', 'hash4', 'activo', 0, 1, 1, 0),
                (5, 1, 4, 'Paciente', 'Dos', 'paciente2@test.com', '+59170000004', 'hash5', 'activo', 0, 1, 1, 0),
                (6, 2, 2, 'Medico', 'Clinica2', 'medico2@test.com', '+59170000005', 'hash6', 'activo', 0, 1, 1, 0)
                """
            )

            # Pacientes (Paciente 1 y 2 en Clínica 1; Paciente 3 en Clínica 2)
            conn.exec_driver_sql(
                """
                INSERT INTO pacientes (
                    id_paciente, id_clinica, id_usuario, nombres, apellidos, ci,
                    fecha_nacimiento, genero, telefono, estado, alergias, antecedentes_patologicos
                ) VALUES
                (1, 1, 4, 'Paciente', 'Uno', '1234567', '1990-01-01', 'M', '+59170000003', 'ACTIVO', 'Penicilina', 'Diabetes tipo 2'),
                (2, 1, 5, 'Paciente', 'Dos', '7654321', '1985-05-05', 'F', '+59170000004', 'ACTIVO', NULL, NULL),
                (3, 2, NULL, 'Paciente', 'Tres', '9999999', '1995-09-09', 'M', '+59170000006', 'ACTIVO', NULL, NULL)
                """
            )

            # Perfil Médico (Médico 1 en Clínica 1)
            conn.exec_driver_sql(
                """
                INSERT INTO medicos (
                    id_medico, id_usuario, matricula_profesional, estado
                ) VALUES
                (1, 2, 'MAT-001', 'activo'),
                (2, 6, 'MAT-002', 'activo')
                """
            )

            # Cita en estado atendible para el paciente 1 y medico 1 en Clínica 1
            conn.exec_driver_sql(
                """
                INSERT INTO citas (id_cita, id_paciente, id_medico, estado, modalidad, motivo)
                VALUES (1, 1, 1, 'EN_CONSULTA', 'PRESENCIAL', 'Dolor de cabeza')
                """
            )

    def _override_current_user(self, user_id: int):
        from fastapi import Depends
        from sqlalchemy.orm import joinedload

        def dependency(db: Session = Depends(get_db)):
            return (
                db.query(Usuario)
                .options(joinedload(Usuario.rol))
                .filter(Usuario.id_usuario == user_id)
                .first()
            )

        app.dependency_overrides[get_current_user] = dependency

    def _payload_consulta_base(self):
        return {
            "id_cita": 1,
            "motivo_consulta": "Cefalea intensa y mareos",
            "sintomas": "Dolor pulsátil en región frontal",
            "examen_fisico": "Paciente lúcido, pupilas isocóricas y reactivas",
            "signos_vitales": {
                "presion_sistolica_mmhg": 120,
                "presion_diastolica_mmhg": 80,
                "frecuencia_cardiaca_lpm": 72,
                "temperatura_corporal_c": 36.5,
                "peso_kg": 70.0,
                "talla_cm": 175.0,
            },
            "evolucion": "Paciente refiere cefalea intensa de 2 días de evolución",
            "plan_medico": "Reposo por 48 horas, hidratación y analgésicos",
            "datos_especialidad": {"escala_eva": 6},
            "diagnosticos": [
                {
                    "codigo_cie": "G43.9",
                    "descripcion": "Migraña, no especificada",
                    "tipo": "DEFINITIVO",
                    "observaciones": "Cuadro migrañoso típico",
                }
            ],
        }

    def test_registrar_consulta_valida_con_auditoria(self):
        self._override_current_user(2)  # Médico Clínica 1
        payload = self._payload_consulta_base()

        response = self.client.post("/api/v1/hce/pacientes/1/consultas", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["id_clinica"], 1)
        self.assertEqual(data["id_historia"], 1)
        self.assertEqual(data["id_cita"], 1)
        self.assertEqual(data["id_medico"], 1)
        self.assertEqual(len(data["diagnosticos"]), 1)
        self.assertEqual(data["diagnosticos"][0]["codigo_cie"], "G43.9")
        self.assertAlmostEqual(data["signos_vitales"]["indice_masa_corporal"], 22.86, places=1)

        # La cita fue finalizada
        with self.engine.begin() as conn:
            estado = conn.exec_driver_sql(
                "SELECT estado FROM citas WHERE id_cita = 1"
            ).scalar()
        self.assertEqual(estado, "FINALIZADA")

        # Se insertó traza de auditoría con id_clinica
        with self.engine.begin() as conn:
            count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM auditoria WHERE tabla_afectada = 'consultas' AND accion = 'INSERT' AND id_clinica = 1"
            ).scalar()
        self.assertEqual(count, 1)

    def test_aislamiento_multitenant_rechaza_paciente_otra_clinica(self):
        # Médico 1 (Clínica 1) intenta consultar paciente 3 (Clínica 2)
        self._override_current_user(2)
        response = self.client.get("/api/v1/hce/pacientes/3")
        self.assertEqual(response.status_code, 404)

        # Médico 1 (Clínica 1) intenta registrar consulta para paciente 3 (Clínica 2)
        payload = self._payload_consulta_base()
        response = self.client.post("/api/v1/hce/pacientes/3/consultas", json=payload)
        self.assertEqual(response.status_code, 404)

    def test_registrar_consulta_sin_diagnosticos_falla(self):
        self._override_current_user(2)
        payload = self._payload_consulta_base()
        payload["diagnosticos"] = []

        response = self.client.post("/api/v1/hce/pacientes/1/consultas", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_recepcion_no_puede_registrar_consulta(self):
        self._override_current_user(3)  # Recepción
        payload = self._payload_consulta_base()

        response = self.client.post("/api/v1/hce/pacientes/1/consultas", json=payload)
        self.assertEqual(response.status_code, 403)

    def test_paciente_no_ve_expediente_ajeno(self):
        # Paciente 2 (usuario 5) intenta ver expediente del paciente 1
        self._override_current_user(5)
        response = self.client.get("/api/v1/hce/pacientes/1")
        self.assertEqual(response.status_code, 403)

    def test_paciente_puede_ver_su_propio_expediente(self):
        # Paciente 1 (usuario 4) consulta su propio expediente
        self._override_current_user(4)
        response = self.client.get("/api/v1/hce/pacientes/1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id_paciente"], 1)
        self.assertEqual(data["id_clinica"], 1)

    def test_signos_vitales_fuera_de_rango(self):
        self._override_current_user(2)
        payload = self._payload_consulta_base()
        payload["signos_vitales"]["presion_sistolica_mmhg"] = 500

        response = self.client.post("/api/v1/hce/pacientes/1/consultas", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_obtener_historia_crea_registro_si_no_existe(self):
        self._override_current_user(1)  # Admin
        response = self.client.get("/api/v1/hce/pacientes/1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id_paciente"], 1)
        self.assertEqual(data["id_clinica"], 1)
        self.assertTrue(data["numero_historia"].startswith("HCE-"))
        self.assertEqual(data["alergias"], "Penicilina")


if __name__ == "__main__":
    unittest.main()
