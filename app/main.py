from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.auth.clinicas.router import router as clinicas_router
from app.modules.tenants.tenant_management.router import router as tenant_management_router
from app.modules.tenants.subscription_payments.router import router as subscription_payments_router
from app.modules.tenants.public_onboarding.router import router as public_onboarding_router
from app.modules.tenants.deactivation_requests.router import router as deactivation_requests_router
from app.modules.auth.users_management.router import router as users_management_router
from app.modules.auth.roles_permissions.router import router as roles_permissions_router
from app.modules.auth.audit.router import router as audit_router
from app.modules.medical_records.router import router as medical_records_router
from app.modules.appointments.router import router as appointments_router
from app.modules.analytics.router import router as analytics_router
from app.modules.communications.router import router as communications_router
from app.modules.payments.router import router as payments_router, pago_error_handler
from app.modules.payments.service import PagoError
from app.modules.medical_records.prescriptions.router import prescription_error_handler
from app.modules.medical_records.prescriptions.service import PrescriptionError
from app.modules.medical_records.tratamientos.router import treatment_error_handler
from app.modules.medical_records.tratamientos.service import TreatmentError
from app.modules.backup.router import router as backup_router
from app.modules.backup import scheduler as backup_scheduler
from app.modules.auth.planes.router import router as planes_router, plan_error_handler
from app.modules.auth.planes.service import PlanError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización de servicios: validación criptográfica CU16 y scheduler de backups."""
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
        _log.warning("CU16 startup crypto validation warning: %s", exc)

    backup_scheduler.iniciar()
    yield
    backup_scheduler.detener()


app = FastAPI(
    title="Telemedicina API",
    description="Backend API SaaS Multitenant para la plataforma de Telemedicina",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configuración de CORS - permite cualquier origen (JWT Bearer tokens, no cookies)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def strip_backend_api_prefix(request: Request, call_next):
    """Permite recibir peticiones a través del proxy local /backend-api/* desde celulares en red Wi-Fi."""
    path = request.scope.get("path", "")
    if path == "/backend-api":
        request.scope["path"] = "/"
    elif path.startswith("/backend-api/"):
        request.scope["path"] = path[len("/backend-api"):]
    return await call_next(request)


# Registro de routers de módulos
app.include_router(auth_router)

# Contexto de Tenant y Clínicas (SaaS multitenant)
app.include_router(clinicas_router)
app.include_router(clinicas_router, prefix="/api/v1")
app.include_router(tenant_management_router)
app.include_router(tenant_management_router, prefix="/api/v1")
app.include_router(subscription_payments_router)
app.include_router(subscription_payments_router, prefix="/api/v1")
app.include_router(public_onboarding_router)
app.include_router(deactivation_requests_router)

# Gestión de Usuarios, Roles y Auditoría
app.include_router(users_management_router)
app.include_router(users_management_router, prefix="/auth")
app.include_router(roles_permissions_router)
app.include_router(roles_permissions_router, prefix="/auth")
app.include_router(audit_router)
app.include_router(audit_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/auth")

# Expediente clínico e Historias Clínicas (CU10, CU12, CU13, CU16, CU17, CU28)
app.include_router(medical_records_router)

# Citas, Agenda y Perfil Médico (CU04, CU05, CU08, CU25)
app.include_router(appointments_router)

# Reportes y exportación (CU22/CU27)
app.include_router(analytics_router)

# Teleconsulta y Chat en Tiempo Real (CU14, CU15)
app.include_router(communications_router)
app.include_router(communications_router, prefix="/api/v1")

# Respaldos de base de datos
app.include_router(backup_router)
app.include_router(planes_router)
app.add_exception_handler(PlanError, plan_error_handler)

# Pagos de citas y teleconsultas + comprobantes (CU19)
app.include_router(payments_router)
app.include_router(payments_router, prefix="/api/v1")

# CU16: formato de error uniforme {"detail", "code"}
app.add_exception_handler(PrescriptionError, prescription_error_handler)
app.add_exception_handler(TreatmentError, treatment_error_handler)
# CU19: errores de negocio de pagos con su código HTTP.
app.add_exception_handler(PagoError, pago_error_handler)


@app.get("/", tags=["General"], summary="Health Check")
def health_check():
    """Endpoint de estado del servicio."""
    return {
        "status": "ok",
        "app": "Telemedicina API",
        "version": "1.0.0"
    }
