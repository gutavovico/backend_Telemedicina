from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.auth.tenant.router import router as tenant_router
from app.modules.auth.clinicas.router import router as clinicas_router
from app.modules.auth.users_management.router import router as users_management_router
from app.modules.auth.roles_permissions.router import router as roles_permissions_router
from app.modules.auth.audit.router import router as audit_router
from app.modules.medical_records.router import router as medical_records_router
from app.modules.appointments.router import router as appointments_router
from app.modules.communications.router import router as communications_router
from app.modules.analytics.router import router as analytics_router
from app.modules.medical_records.prescriptions.router import prescription_error_handler
from app.modules.medical_records.prescriptions.service import PrescriptionError

app = FastAPI(
    title="Telemedicina API",
    description="Backend API para la plataforma de Telemedicina",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configuración de CORS - permite cualquier origen (JWT Bearer tokens, no cookies)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro de routers de módulos
app.include_router(auth_router)

# Contexto de Tenant y Clínicas (SaaS multitenant)
app.include_router(tenant_router)
app.include_router(tenant_router, prefix="/api/v1")
app.include_router(clinicas_router)
app.include_router(clinicas_router, prefix="/api/v1")

# Gestión de Usuarios, Roles y Auditoría
app.include_router(users_management_router)
app.include_router(users_management_router, prefix="/auth")
app.include_router(users_management_router, prefix="/api/v1")
app.include_router(roles_permissions_router)
app.include_router(roles_permissions_router, prefix="/auth")
app.include_router(roles_permissions_router, prefix="/api/v1")
app.include_router(audit_router)
app.include_router(audit_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/auth")

# Expediente clínico e Historias Clínicas (CU03, CU09, CU10, CU12, CU13, CU16, CU28)
app.include_router(medical_records_router)

# Citas, Agenda y Perfil Médico (CU04, CU05, CU08, CU25)
app.include_router(appointments_router)

# Teleconsulta y Chat en Tiempo Real (CU15)
app.include_router(communications_router)
app.include_router(communications_router, prefix="/api/v1")

# Reportes y Exportación Analítica (CU22, CU27)
app.include_router(analytics_router)
app.include_router(analytics_router, prefix="/api/v1")

# CU16: formato de error uniforme {"detail", "code"}
app.add_exception_handler(PrescriptionError, prescription_error_handler)



@app.get("/", tags=["General"], summary="Health Check")
def health_check():
    """Endpoint de estado del servicio."""
    return {
        "status": "ok",
        "app": "Telemedicina API",
        "version": "1.0.0"
    }

