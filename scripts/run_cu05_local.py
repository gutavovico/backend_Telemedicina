"""Demo CU5 loopback, SQLite en memoria. No usa ni modifica Neon ni .env.

Ejecutar desde backend_Telemedicina con ../.venv/Scripts/python.exe scripts/run_cu05_local.py.
Usuarios: u1@example.com (admin), u2@example.com (médico),
u3@example.com (recepción), u4@example.com (paciente). Password: Cu5-local-2026!
La autenticación y autorización son las reales; sólo get_db usa la fixture SQLite.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "tests")]
    # Sobrescribir antes de importar Settings: cualquier conexión accidental
    # a PostgreSQL se dirige a loopback, nunca al destino del .env.
    os.environ.update(DB_HOST="127.0.0.1", DB_PORT="1", DB_USER="cu05_demo",
                      DB_PASSWORD=secrets.token_urlsafe(24), DB_NAME="cu05_demo",
                      JWT_SECRET_KEY=secrets.token_urlsafe(48),
                      JWT_REFRESH_SECRET_KEY=secrets.token_urlsafe(48),
                      CORS_ORIGINS="http://localhost:4200", EMAIL_ENABLED="false")
    key = Ed25519PrivateKey.generate()
    os.environ["PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64"] = base64.b64encode(key.private_bytes_raw()).decode()
    os.environ["PRESCRIPTION_SIGNING_KEY_ID"] = "cu05-local-ephemeral"
    os.environ["PRESCRIPTION_VERIFICATION_KEYS_JSON"] = json.dumps({
        "cu05-local-ephemeral": base64.b64encode(key.public_key().public_bytes_raw()).decode()})
    os.environ["PRESCRIPTION_TELEMETRY_HMAC_KEY"] = secrets.token_urlsafe(48)
    os.environ["PRESCRIPTION_DEFAULT_VALIDITY_DAYS"] = "90"

    from sqlalchemy import text
    from app.main import app
    from app.core.security import hash_password
    from app.modules.auth.dependencies import get_current_user
    from app.modules.auth.models import TokenBlacklist
    from test_cu05_medical_agenda import CU05TextHoursTestCase
    import uvicorn

    fixture = CU05TextHoursTestCase
    fixture.setUpClass()
    # Logout CU24 necesita esta tabla; crearla sólo en el engine SQLite de la demo.
    TokenBlacklist.__table__.create(bind=fixture.engine, checkfirst=True)
    seed = fixture()
    seed.setUp()
    seed.clock.stop()  # Usar la fecha real de Bolivia durante la demo.
    app.dependency_overrides.pop(get_current_user, None)
    with fixture.engine.begin() as conn:
        conn.execute(text("UPDATE usuarios SET correo='u' || id_usuario || '@example.com', password_hash=:hash"),
                     {"hash": hash_password("Cu5-local-2026!")})
        conn.exec_driver_sql("UPDATE usuarios SET nombres='Demo', apellidos='CU5'")
    print("DEMO AISLADA CU5: SQLite en memoria; cambios descartados al detener.")
    print("Usuarios u1/u2/u3/u4@example.com; password Cu5-local-2026!")
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000)
    finally:
        fixture.tearDownClass()


if __name__ == "__main__":
    main()
