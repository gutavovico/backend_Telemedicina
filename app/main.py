from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.medical_records.router import router as medical_records_router
from app.modules.appointments.router import router as appointments_router
from app.modules.communications.router import router as communications_router
from app.modules.medical_records.prescriptions.router import prescription_error_handler
from app.modules.medical_records.prescriptions.service import PrescriptionError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validación criptográfica CU16 durante startup (contrato §5, diseño 2).

    La aplicación falla explícitamente si falta la clave privada activa,
    la clave es inválida, falta `key_id`, el activo no aparece en el anillo,
    la pública no corresponde con la privada o el anillo es inválido.
    También valida `PRESCRIPTION_DEFAULT_VALIDITY_DAYS` (1-90).
    Las pruebas pueden proveer configuración válida antes de crear el
    cliente (`with TestClient(app)` ejecuta este lifespan). Nunca se
    registran ni muestran claves privadas en logs o errores.
    """
    import logging

    _log = logging.getLogger(__name__)
    try:
        from app.modules.medical_records.prescriptions.crypto import (
            ensure_prescription_crypto_configured,
        )
        from app.modules.medical_records.prescriptions.service import (
            _global_vigencia_maxima,
        )

        ensure_prescription_crypto_configured()
        _global_vigencia_maxima()
    except Exception as exc:
        # Sin material sensible: solo tipo y mensaje genérico de dominio.
        _log.error("CU16 startup validation failed: %s", type(exc).__name__)
        raise
    yield


app = FastAPI(
    title="Telemedicina API",
    description="Backend API SaaS Multitenant para la plataforma de Telemedicina",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro de routers canónicos activos (Arquitectura Sección 3.9)
app.include_router(auth_router)
app.include_router(medical_records_router)
app.include_router(appointments_router)
app.include_router(communications_router)
app.include_router(communications_router, prefix="/api/v1")

# CU16: formato de error uniforme {"detail", "code"} (contrato §7)
app.add_exception_handler(PrescriptionError, prescription_error_handler)


@app.get("/", tags=["General"], summary="Health Check")
def health_check():
    """Endpoint de estado del servicio."""
    return {
        "status": "ok",
        "app": "Telemedicina API",
        "version": "1.0.0"
    }
