"""Backend normal CU05 con el Neon de .env; solo loopback, sin READ ONLY.

Ejecutar: ../.venv/Scripts/python.exe -m scripts.run_cu05_neon
El arranque valida CU16 mediante app.main, sin sustituir claves ni crear tablas.
"""
from app.core.config import settings


def main() -> None:
    if not settings.DB_HOST.lower().endswith(".neon.tech"):
        raise SystemExit("El destino configurado no es Neon; servidor no iniciado.")
    if "http://localhost:4200" not in settings.cors_origins_list:
        raise SystemExit("CORS no permite Angular local; servidor no iniciado.")
    import uvicorn

    print("CU05 Neon: app normal con escritura habilitada, solo 127.0.0.1:8000.")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
