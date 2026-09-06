from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.medical_records.router import router as medical_records_router
from app.modules.appointments.router import router as appointments_router

app = FastAPI(
    title="Telemedicina API",
    description="Backend API SaaS Multitenant para la plataforma de Telemedicina",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro de routers canónicos activos (Arquitectura Sección 3.9)
app.include_router(auth_router)
app.include_router(medical_records_router)
app.include_router(appointments_router)


@app.get("/", tags=["General"], summary="Health Check")
def health_check():
    """Endpoint de estado del servicio."""
    return {
        "status": "ok",
        "app": "Telemedicina API",
        "version": "1.0.0"
    }
