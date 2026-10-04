import unittest
from datetime import date, datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user, get_required_tenant_id
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.appointments.models import Especialidad, Medico, MedicoEspecialidad, Cita
from app.modules.medical_records.models import Paciente
from app.modules.communications.models import MensajeChatCita


class CU15TeleconsultaTestCase(unittest.TestCase):
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
        self._mock_user(self.user_paciente, tenant_id=self.clinica_id)

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_required_tenant_id, None)

    def _mock_user(self, user: Usuario, tenant_id: int):
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_required_tenant_id] = lambda: tenant_id

    def _reset_data(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM mensajes_chat_cita")
            conn.exec_driver_sql("DELETE FROM citas")
            conn.exec_driver_sql("DELETE FROM medico_especialidad")
            conn.exec_driver_sql("DELETE FROM especialidades")
            conn.exec_driver_sql("DELETE FROM medicos")
            conn.exec_driver_sql("DELETE FROM pacientes")
            conn.exec_driver_sql("DELETE FROM usuarios")
            conn.exec_driver_sql("DELETE FROM roles")
            conn.exec_driver_sql("DELETE FROM clinicas")

    def _seed_data(self):
        self.clinica_id = 1
        db = self.SessionLocal()
        try:
            self.clinica = Clinica(
                id_clinica=self.clinica_id,
                nombre="Hospital San Juan de Dios",
                correo="contacto@sanjuandedios.org",
                estado="ACTIVO",
            )
            db.add(self.clinica)

            self.rol_admin = Rol(id_rol=1, nombre="ADMIN", estado="ACTIVO")
            self.rol_medico = Rol(id_rol=2, nombre="MEDICO", estado="ACTIVO")
            self.rol_paciente = Rol(id_rol=4, nombre="PACIENTE", estado="ACTIVO")
            db.add_all([self.rol_admin, self.rol_medico, self.rol_paciente])
            db.flush()

            self.user_admin = Usuario(
                id_usuario=1,
                id_clinica=1,
                id_rol=1,
                nombres="Admin",
                apellidos="Sistema",
                correo="admin@sanjuandedios.org",
                password_hash="secret",
                estado="activo",
            )
            self.user_medico = Usuario(
                id_usuario=2,
                id_clinica=1,
                id_rol=2,
                nombres="Ana",
                apellidos="López",
                correo="ana.lopez@sanjuandedios.org",
                password_hash="secret",
                estado="activo",
            )
            self.user_paciente = Usuario(
                id_usuario=3,
                id_clinica=1,
                id_rol=4,
                nombres="Carlos",
                apellidos="Pérez",
                correo="carlito77769@gmail.com",
                password_hash="secret",
                estado="activo",
            )
            self.user_ajeno = Usuario(
                id_usuario=4,
                id_clinica=1,
                id_rol=4,
                nombres="Pedro",
                apellidos="Ajeno",
                correo="pedro@gmail.com",
                password_hash="secret",
                estado="activo",
            )
            db.add_all([self.user_admin, self.user_medico, self.user_paciente, self.user_ajeno])
            db.flush()

            self.paciente = Paciente(
                id_paciente=10,
                id_usuario=self.user_paciente.id_usuario,
                nombres="Carlos",
                apellidos="Pérez",
                ci="12345678",
                complemento="LP",
                fecha_nacimiento=date(1985, 3, 20),
                genero="M",
                telefono="+591 71234567",
                seguro_medico="Sanitas Plus",
                numero_seguro="SP-998877",
                estado="ACTIVO",
            )
            db.add(self.paciente)

            self.medico = Medico(
                id_medico=42,
                id_clinica=1,
                id_usuario=self.user_medico.id_usuario,
                matricula_profesional="MED-12345",
                descripcion_profesional="Dra. Ana López es especialista en medicina general.",
                experiencia="10 años de experiencia",
                estado="activo",
            )
            db.add(self.medico)
            db.flush()

            self.esp = Especialidad(
                id_especialidad=1,
                nombre="Medicina General",
                descripcion="Atención integral",
                estado="activo",
            )
            db.add(self.esp)
            db.flush()

            db.add(MedicoEspecialidad(id_medico=self.medico.id_medico, id_especialidad=self.esp.id_especialidad, es_principal=True))

            self.cita = Cita(
                id_cita=105,
                id_clinica=1,
                id_paciente=self.paciente.id_paciente,
                id_medico=self.medico.id_medico,
                id_especialidad=self.esp.id_especialidad,
                fecha_cita=date(2024, 9, 2),
                hora_inicio="17:00",
                hora_fin="17:30",
                modalidad="TELEMEDICINA",
                estado="CONFIRMADA",
            )
            db.add(self.cita)
            db.commit()
        finally:
            db.close()

    def test_obtener_teleconsulta_paciente_exito(self):
        """Verifica que el paciente titular puede obtener la vista completa de teleconsulta."""
        response = self.client.get(f"/citas/{self.cita.id_cita}/teleconsulta")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["nombreClinica"], "Hospital San Juan de Dios")
        self.assertEqual(data["usuarioActivo"]["idUsuario"], self.user_paciente.id_usuario)
        self.assertEqual(data["paciente"]["nombreCompleto"], "Carlos Pérez")
        self.assertEqual(data["cita"]["idCita"], self.cita.id_cita)
        self.assertEqual(data["medico"]["idMedico"], self.medico.id_medico)
        self.assertTrue(len(data["mensajes"]) >= 1)

    def test_enviar_mensaje_chat_paciente(self):
        """Verifica que el paciente puede enviar mensajes en el chat de la cita."""
        payload = {
            "idCita": self.cita.id_cita,
            "contenido": "¿Tengo que mantener el ayuno antes de la prueba?",
        }
        response = self.client.post(f"/citas/{self.cita.id_cita}/chat/mensajes", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()

        self.assertEqual(data["contenido"], "¿Tengo que mantener el ayuno antes de la prueba?")
        self.assertEqual(data["idRemitente"], self.user_paciente.id_usuario)
        self.assertEqual(data["rolRemitente"], "PACIENTE")
        self.assertTrue(data["esPropio"])

        # Verificar que ahora aparece en el listado de teleconsulta
        res_get = self.client.get(f"/citas/{self.cita.id_cita}/teleconsulta")
        self.assertEqual(res_get.status_code, 200)
        mensajes = res_get.json()["mensajes"]
        self.assertTrue(any(m["contenido"] == payload["contenido"] for m in mensajes))

    def test_enviar_mensaje_chat_medico(self):
        """Verifica que el médico tratante puede enviar mensajes y su rol es MEDICO."""
        self._mock_user(self.user_medico, tenant_id=self.clinica_id)
        payload = {
            "idCita": self.cita.id_cita,
            "contenido": "Hola Carlos, sí, por favor mantenga 8 horas de ayuno.",
        }
        response = self.client.post(f"/citas/{self.cita.id_cita}/chat/mensajes", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()

        self.assertEqual(data["rolRemitente"], "MEDICO")
        self.assertEqual(data["idRemitente"], self.user_medico.id_usuario)

    def test_teleconsulta_bloqueo_acceso_ajeno(self):
        """Verifica que un usuario no participante recibe 403 Forbidden."""
        self._mock_user(self.user_ajeno, tenant_id=self.clinica_id)
        response = self.client.get(f"/citas/{self.cita.id_cita}/teleconsulta")
        self.assertEqual(response.status_code, 403)

    def test_obtener_mi_teleconsulta_activa(self):
        """Verifica que el endpoint /citas/me/teleconsulta localiza la cita activa del paciente."""
        response = self.client.get("/citas/me/teleconsulta")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["cita"]["idCita"], self.cita.id_cita)
        self.assertEqual(data["paciente"]["nombreCompleto"], "Carlos Pérez")

    def test_enviar_mensaje_contenido_vacio(self):
        """Verifica que enviar un mensaje vacío o con espacios responde 400 Bad Request."""
        payload = {"idCita": self.cita.id_cita, "contenido": "   "}
        response = self.client.post(f"/citas/{self.cita.id_cita}/chat/mensajes", json=payload)
        self.assertEqual(response.status_code, 400)

    def test_aislamiento_multitenant(self):
        """Verifica que acceder a una cita desde un tenant diferente responde 404 Not Found."""
        self._mock_user(self.user_paciente, tenant_id=999)
        response = self.client.get(f"/citas/{self.cita.id_cita}/teleconsulta")
        self.assertEqual(response.status_code, 404)

    def test_rutas_con_prefijo_api_v1(self):
        """Verifica que los endpoints también responden bajo /api/v1/citas/."""
        response = self.client.get(f"/api/v1/citas/{self.cita.id_cita}/teleconsulta")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["cita"]["idCita"], self.cita.id_cita)


if __name__ == "__main__":
    unittest.main()
