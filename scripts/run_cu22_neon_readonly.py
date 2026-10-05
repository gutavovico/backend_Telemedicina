"""Local CU22 Analytics read-only review against configured Neon.

The normal ASGI app and CU16 startup validation use the backend .env unchanged.
Read-only database transactions do not isolate CU16 cryptographic routes.
Do not expose this server publicly or use it for routes that write.
"""

from sqlalchemy import event


def main() -> None:
    from app.core.config import settings

    if not settings.DB_HOST.lower().endswith(".neon.tech"):
        raise SystemExit("La configuración no identifica un host de Neon; no se arranca.")
    if "http://localhost:4200" not in settings.cors_origins_list:
        raise SystemExit("CORS no permite http://localhost:4200; no se arranca.")

    from app.core.database import engine

    @event.listens_for(engine, "connect")
    def readonly_connection(dbapi_connection, _record) -> None:
        # psycopg2 applies this to every transaction on the pooled connection.
        dbapi_connection.set_session(readonly=True, autocommit=False)

    import uvicorn

    print("CU22 Neon local: backend real, transacciones READ ONLY, loopback:8000.")
    print("Solo pruebas de lectura de Analytics; CU16 requiere configuración válida del backend.")
    print("No usar recetas, logout ni otras rutas que escriben.")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
