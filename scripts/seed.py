import sys
import os

# Asegurar que la raíz del proyecto esté en el PYTHONPATH
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Usuario
from app.modules.medicos.models import Especialidad, Medico, MedicoEspecialidad

# Lista de usuarios iniciales para el seed
SEED_USERS = [
    {
        "nombres": "Admin",
        "apellidos": "Sistema",
        "correo": "admin@telemedicina.com",
        "password": "admin123",
        "telefono": "+591 70000000",
        "foto_perfil": None,
        "estado": "activo",
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "nombres": "Doctor",
        "apellidos": "Prueba",
        "correo": "doctor@telemedicina.com",
        "password": "doctor123",
        "telefono": "+591 71111111",
        "foto_perfil": None,
        "estado": "activo",
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    }
]

# Catálogo base de especialidades (CU04)
SEED_ESPECIALIDADES = [
    {"nombre": "Medicina General", "descripcion": "Atención primaria y consulta general"},
    {"nombre": "Cardiología", "descripcion": "Diagnóstico y tratamiento de enfermedades del corazón"},
    {"nombre": "Pediatría", "descripcion": "Atención médica de niños y adolescentes"},
    {"nombre": "Dermatología", "descripcion": "Tratamiento de enfermedades de la piel"},
    {"nombre": "Ginecología", "descripcion": "Salud de la mujer y obstetricia"},
    {"nombre": "Traumatología", "descripcion": "Lesiones y enfermedades del sistema musculoesquelético"},
    {"nombre": "Neurología", "descripcion": "Trastornos del sistema nervioso"},
    {"nombre": "Psiquiatría", "descripcion": "Salud mental y trastornos psiquiátricos"},
]

# Perfil médico para el usuario doctor@telemedicina.com (CU04)
SEED_MEDICO = {
    "correo_usuario": "doctor@telemedicina.com",
    "matricula_profesional": "MAT-00001",
    "descripcion_profesional": "Médico cirujano con 10 años de experiencia en consulta general y urgencias.",
    "experiencia": "Hospital San Juan de Dios, 2016-2026. Consulta externa y guardias de urgencias.",
    "especialidad_principal": "Medicina General",
}


def seed_database():
    """Ejecuta el sembrado de datos en la base de datos de manera idempotente (upsert)."""
    db = SessionLocal()
    print("[INFO] Iniciando seed de la base de datos...")

    try:
        # 1. Usuarios
        for user_data in SEED_USERS:
            correo = user_data["correo"].lower().strip()
            existing_user = db.query(Usuario).filter(Usuario.correo == correo).first()

            if existing_user:
                # Actualizar usuario existente (Upsert)
                existing_user.nombres = user_data["nombres"]
                existing_user.apellidos = user_data["apellidos"]
                existing_user.password_hash = hash_password(user_data["password"])
                existing_user.telefono = user_data["telefono"]
                existing_user.foto_perfil = user_data["foto_perfil"]
                existing_user.estado = user_data["estado"]
                existing_user.notificaciones_push = user_data["notificaciones_push"]
                existing_user.notificaciones_email = user_data["notificaciones_email"]
                existing_user.notificaciones_sms = user_data["notificaciones_sms"]
                print(f"  [ACTUALIZADO] Usuario existente: {correo}")
            else:
                # Crear nuevo usuario
                new_user = Usuario(
                    nombres=user_data["nombres"],
                    apellidos=user_data["apellidos"],
                    correo=correo,
                    password_hash=hash_password(user_data["password"]),
                    telefono=user_data["telefono"],
                    foto_perfil=user_data["foto_perfil"],
                    estado=user_data["estado"],
                    notificaciones_push=user_data["notificaciones_push"],
                    notificaciones_email=user_data["notificaciones_email"],
                    notificaciones_sms=user_data["notificaciones_sms"],
                )
                db.add(new_user)
                print(f"  [CREADO] Nuevo usuario: {correo}")

        db.flush()

        # 2. Especialidades (CU04)
        for esp_data in SEED_ESPECIALIDADES:
            existing_esp = (
                db.query(Especialidad)
                .filter(Especialidad.nombre.ilike(esp_data["nombre"]))
                .first()
            )
            if existing_esp:
                existing_esp.descripcion = esp_data["descripcion"]
                existing_esp.estado = "activo"
                print(f"  [ACTUALIZADO] Especialidad existente: {esp_data['nombre']}")
            else:
                db.add(Especialidad(nombre=esp_data["nombre"], descripcion=esp_data["descripcion"], estado="activo"))
                print(f"  [CREADO] Nueva especialidad: {esp_data['nombre']}")

        db.flush()

        # 3. Perfil médico del usuario doctor (CU04)
        doctor = (
            db.query(Usuario)
            .filter(Usuario.correo == SEED_MEDICO["correo_usuario"])
            .first()
        )
        if doctor:
            medico = db.query(Medico).filter(Medico.id_usuario == doctor.id_usuario).first()
            if not medico:
                medico = Medico(
                    id_usuario=doctor.id_usuario,
                    matricula_profesional=SEED_MEDICO["matricula_profesional"],
                    descripcion_profesional=SEED_MEDICO["descripcion_profesional"],
                    experiencia=SEED_MEDICO["experiencia"],
                    estado="activo",
                )
                db.add(medico)
                print(f"  [CREADO] Perfil médico para: {SEED_MEDICO['correo_usuario']}")
            else:
                medico.matricula_profesional = SEED_MEDICO["matricula_profesional"]
                medico.descripcion_profesional = SEED_MEDICO["descripcion_profesional"]
                medico.experiencia = SEED_MEDICO["experiencia"]
                medico.estado = "activo"
                print(f"  [ACTUALIZADO] Perfil médico existente: {SEED_MEDICO['correo_usuario']}")

            db.flush()

            especialidad_ppal = (
                db.query(Especialidad)
                .filter(Especialidad.nombre.ilike(SEED_MEDICO["especialidad_principal"]))
                .first()
            )
            if especialidad_ppal:
                asociacion = (
                    db.query(MedicoEspecialidad)
                    .filter(
                        MedicoEspecialidad.id_medico == medico.id_medico,
                        MedicoEspecialidad.id_especialidad == especialidad_ppal.id_especialidad,
                    )
                    .first()
                )
                if not asociacion:
                    # Asegurar que solo exista una principal
                    db.query(MedicoEspecialidad).filter(
                        MedicoEspecialidad.id_medico == medico.id_medico,
                        MedicoEspecialidad.es_principal.is_(True),
                    ).update({"es_principal": False}, synchronize_session=False)
                    db.add(
                        MedicoEspecialidad(
                            id_medico=medico.id_medico,
                            id_especialidad=especialidad_ppal.id_especialidad,
                            es_principal=True,
                        )
                    )
                    print(f"  [CREADA] Asignación de especialidad principal: {SEED_MEDICO['especialidad_principal']}")
                else:
                    asociacion.es_principal = True
                    print(f"  [OK] Especialidad principal ya asignada: {SEED_MEDICO['especialidad_principal']}")

        db.commit()
        print("[EXITO] Seed completado correctamente.")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error durante el seed: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
