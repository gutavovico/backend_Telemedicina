from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.medical_records.router import router as medical_records_router
from app.modules.appointments.router import router as appointments_router
from app.modules.medical_records.patient_profile.router import router as patients_router
from app.modules.medical_records.hce.router import router as hce_router
from app.modules.medical_records.fichas.router import router as fichas_router
from app.modules.auth.tenant.router import router as tenant_router
from app.modules.auth.clinicas.router import router as clinicas_router
from app.modules.auth.users_management.router import router as users_router
from app.modules.auth.roles_permissions.router import router as roles_router
from app.modules.auth.audit.router import router as audit_router
from app.modules.communications.router import router as communications_router
from app.modules.analytics.router import router as analytics_router

app = FastAPI(
    title="Telemedicina API",
    description="Backend API para la plataforma de Telemedicina",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ConfiguraciÃ³n de CORS - permite cualquier origen (JWT Bearer tokens, no cookies)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro de routers de mÃ³dulos
app.include_router(auth_router)
app.include_router(medical_records_router)
app.include_router(communications_router)
app.include_router(appointments_router)
app.include_router(patients_router)
app.include_router(hce_router)
app.include_router(fichas_router, prefix="/api/v1/fichas")
app.include_router(tenant_router, prefix="/api/v1")
app.include_router(clinicas_router, prefix="/api/v1")
app.include_router(users_router)
app.include_router(roles_router)
app.include_router(audit_router, prefix="/api/v1")
app.include_router(analytics_router)


@app.get("/", tags=["General"], summary="Health Check")
def health_check():
    """Endpoint de estado del servicio."""
    return {
        "status": "ok",
        "app": "Telemedicina API",
        "version": "1.0.0"
    }

