"""CU22/CU27 browser fixture: real API, ephemeral SQLite, no Neon connection.

Run from backend_Telemedicina with ../.venv/Scripts/python.exe scripts/run_cu22_local.py.
Accounts: admin1@example.com, admin2@example.com, medico@example.com,
recepcion@example.com, paciente@example.com. Password: Cu22-local-2026!
Only get_db is overridden. Login, auth/me, authorization, queries and export are real.
"""

import base64
from datetime import date, timedelta
import json
import os
from pathlib import Path
import secrets
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _safe_environment() -> None:
    # Must run before importing app.core.config/database or the CU05 fixture.
    os.environ.update(
        DB_HOST="127.0.0.1", DB_PORT="1", DB_USER="cu22_local",
        DB_PASSWORD=secrets.token_urlsafe(24), DB_NAME="cu22_local",
        JWT_SECRET_KEY=secrets.token_urlsafe(48),
        JWT_REFRESH_SECRET_KEY=secrets.token_urlsafe(48),
        CORS_ORIGINS="http://localhost:4200,http://127.0.0.1:4200",
        EMAIL_ENABLED="false",
    )
    key = Ed25519PrivateKey.generate()
    key_id = "cu22-local-ephemeral"
    os.environ["PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64"] = base64.b64encode(
        key.private_bytes_raw()).decode()
    os.environ["PRESCRIPTION_SIGNING_KEY_ID"] = key_id
    os.environ["PRESCRIPTION_VERIFICATION_KEYS_JSON"] = json.dumps({
        key_id: base64.b64encode(key.public_key().public_bytes_raw()).decode()
    })
    os.environ["PRESCRIPTION_TELEMETRY_HMAC_KEY"] = secrets.token_urlsafe(48)
    os.environ["PRESCRIPTION_DEFAULT_VALIDITY_DAYS"] = "90"


def _add_reports_data(engine, password_hash: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE clinicas ADD COLUMN estado TEXT NOT NULL DEFAULT 'ACTIVO'")
        conn.exec_driver_sql("ALTER TABLE citas ADD COLUMN modalidad TEXT")
        conn.exec_driver_sql(
            "CREATE TABLE historias_clinicas (id_historia INTEGER PRIMARY KEY, "
            "id_clinica INTEGER NOT NULL, id_paciente INTEGER NOT NULL)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE consultas (id_consulta INTEGER PRIMARY KEY, id_clinica INTEGER NOT NULL, "
            "id_historia INTEGER NOT NULL, id_cita INTEGER NOT NULL, id_medico INTEGER NOT NULL, "
            "fecha_consulta DATETIME NOT NULL)"
        )
        conn.execute(text("UPDATE usuarios SET password_hash=:hash"), {"hash": password_hash})
        for uid, email, first, last in (
            (1, "admin1@example.com", "Administradora", "Central"),
            (2, "medico@example.com", "María", "Álvarez"),
            (3, "recepcion@example.com", "Recepción", "Central"),
            (4, "paciente@example.com", "Paciente", "Central"),
            (5, "medico2@example.com", "Luis", "Ajeno"),
            (7, "admin2@example.com", "Administrador", "Otra Clínica"),
        ):
            conn.execute(text(
                "UPDATE usuarios SET correo=:email, nombres=:first, apellidos=:last WHERE id_usuario=:uid"
            ), {"email": email, "first": first, "last": last, "uid": uid})
        conn.exec_driver_sql(
            "INSERT INTO especialidades (id_especialidad,nombre,estado) VALUES "
            "(5,'Cardiología','activo'),(6,'Dermatología','activo')"
        )
        conn.exec_driver_sql(
            "INSERT INTO historias_clinicas VALUES (400,1,40),(401,1,41),(900,2,90)"
        )
        for index in range(14):
            day = date(2026, 9, 1) + timedelta(days=index)
            patient = 41 if index % 3 == 0 else 40
            state = "CANCELADA" if index in (3, 9) else "FINALIZADA"
            specialty = None if index == 6 else 5
            mode = "TELEMEDICINA" if index % 2 == 0 else "PRESENCIAL"
            conn.execute(text(
                "INSERT INTO citas (id_cita,id_paciente,id_medico,id_especialidad,fecha_cita,"
                "hora_inicio,hora_fin,estado,tipo_consulta,modalidad) VALUES "
                "(:id,:patient,20,:specialty,:day,'09:00:00','09:30:00',:state,:mode,:mode)"
            ), {"id": 100 + index, "patient": patient, "specialty": specialty,
                "day": day, "state": state, "mode": mode})
            if state != "CANCELADA":
                history = 401 if patient == 41 else 400
                conn.execute(text(
                    "INSERT INTO consultas VALUES (:id,1,:history,:appointment,20,:timestamp)"
                ), {"id": 1000 + index, "history": history, "appointment": 100 + index,
                    "timestamp": f"{day} 10:00:00"})
        # A second consultation for one appointment must not inflate global encounters.
        conn.exec_driver_sql(
            "INSERT INTO consultas VALUES (1100,1,401,100,20,'2026-09-01 11:00:00')"
        )
        for index in range(4):
            day = date(2026, 9, 1) + timedelta(days=index)
            conn.execute(text(
                "INSERT INTO citas (id_cita,id_paciente,id_medico,id_especialidad,fecha_cita,"
                "hora_inicio,hora_fin,estado,tipo_consulta,modalidad) VALUES "
                "(:id,90,50,6,:day,'11:00:00','11:30:00','FINALIZADA','PRESENCIAL','PRESENCIAL')"
            ), {"id": 200 + index, "day": day})
            conn.execute(text(
                "INSERT INTO consultas VALUES (:id,2,900,:appointment,50,:timestamp)"
            ), {"id": 2000 + index, "appointment": 200 + index,
                "timestamp": f"{day} 12:00:00"})


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "tests")]
    _safe_environment()

    from app.core.config import settings
    from app.core.database import get_db
    from app.core.security import hash_password
    from app.main import app
    from app.modules.auth.dependencies import get_current_user
    from app.modules.auth.models import TokenBlacklist
    from test_cu05_medical_agenda import CU05TextHoursTestCase
    import uvicorn

    assert settings.DB_HOST == "127.0.0.1" and settings.DB_PORT == 1
    fixture = CU05TextHoursTestCase
    fixture.setUpClass()
    TokenBlacklist.__table__.create(bind=fixture.engine, checkfirst=True)
    seed = fixture()
    seed.setUp()
    seed.clock.stop()
    app.dependency_overrides.pop(get_current_user, None)
    assert get_db in app.dependency_overrides
    _add_reports_data(fixture.engine, hash_password("Cu22-local-2026!"))
    print("CU22/CU27 aislado: API real y SQLite en memoria, sin conexión a Neon.", flush=True)
    print("admin1/admin2/medico/recepcion/paciente@example.com; clave Cu22-local-2026!", flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
    finally:
        fixture.tearDownClass()


if __name__ == "__main__":
    main()
