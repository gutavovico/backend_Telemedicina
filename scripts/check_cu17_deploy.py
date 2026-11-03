"""Read-only CU17 deployment check: python -m scripts.check_cu17_deploy."""

import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import inspect, select, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.auth.models import Rol, Usuario
from app.modules.medical_records.tratamientos import avisos
from app.modules.medical_records.tratamientos.avisos_models import TratamientoDispositivo


CU17_TABLES = {
    "tratamientos",
    "tratamiento_medicamentos",
    "tratamiento_dosis",
    "tratamiento_eventos",
    "tratamiento_operaciones_dosis",
    "tratamiento_avisos",
    "tratamiento_dispositivos",
    "tratamiento_entregas_push",
    "tratamiento_cursores",
}


def check() -> list[str]:
    problems: list[str] = []
    if not avisos.push_configurado():
        problems.append("FCM no esta configurado o la clave de dispositivos no es valida")

    credentials_path = Path(settings.CU17_FCM_SERVICE_ACCOUNT_FILE)
    if credentials_path.is_file():
        try:
            with credentials_path.open(encoding="utf-8") as source:
                credential_project = json.load(source).get("project_id")
            if credential_project != settings.CU17_FCM_PROJECT_ID:
                problems.append("El proyecto FCM no coincide con la cuenta de servicio")
        except (OSError, ValueError, TypeError):
            problems.append("El archivo de cuenta de servicio no se puede leer")

    try:
        mapping = json.loads(settings.CU17_SYSTEM_USER_IDS_JSON)
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("empty mapping")
        system_users = {int(clinic): int(user) for clinic, user in mapping.items()}
        if any(clinic <= 0 or user <= 0 for clinic, user in system_users.items()):
            raise ValueError("invalid id")
    except (ValueError, TypeError):
        system_users = {}
        problems.append("CU17_SYSTEM_USER_IDS_JSON no contiene un mapa valido de clinicas")

    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        expected_revisions = set(ScriptDirectory.from_config(config).get_heads())
        with SessionLocal() as db:
            actual_revisions = set(db.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if actual_revisions != expected_revisions:
                problems.append("La base no esta en el head de Alembic")
            missing = CU17_TABLES - set(inspect(db.get_bind()).get_table_names())
            if missing:
                problems.append("Faltan tablas CU17: " + ", ".join(sorted(missing)))
            for clinic_id, user_id in system_users.items():
                row = db.execute(
                    select(Usuario.id_clinica, Usuario.estado, Rol.nombre, Rol.estado)
                    .join(Rol, Rol.id_rol == Usuario.id_rol)
                    .where(Usuario.id_usuario == user_id)
                ).first()
                if (row is None or row[0] != clinic_id or
                        str(row[1]).upper() != "ACTIVO" or
                        str(row[2]).upper() != "SISTEMA" or
                        str(row[3]).upper() != "ACTIVO"):
                    problems.append(f"Usuario SISTEMA invalido para clinica {clinic_id}")
            ciphertext = db.execute(
                select(TratamientoDispositivo.token_cifrado)
                .where(TratamientoDispositivo.activo.is_(True))
                .limit(1)
            ).scalar_one_or_none()
            if ciphertext and avisos.push_configurado():
                try:
                    Fernet(settings.CU17_DEVICE_TOKEN_KEY.get_secret_value().encode("ascii")).decrypt(
                        ciphertext.encode("ascii")
                    )
                except (InvalidToken, ValueError, UnicodeError):
                    problems.append("CU17_DEVICE_TOKEN_KEY no descifra un dispositivo existente")
    except Exception as error:
        problems.append(f"No se pudo comprobar la base: {type(error).__name__}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        for problem in problems:
            print("CU17_ERROR: " + problem)
        return 1
    print("CU17_OK: configuracion, migracion, usuario SISTEMA y cifrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
