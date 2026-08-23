import sys
import os

# Asegurar que la raíz del proyecto esté en el PYTHONPATH
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Usuario

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


def seed_database():
    """Ejecuta el sembrado de datos en la base de datos de manera idempotente (upsert)."""
    db = SessionLocal()
    print("[INFO] Iniciando seed de la base de datos...")

    try:
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
