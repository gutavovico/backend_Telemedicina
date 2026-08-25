from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.roles.router import router as roles_router
from app.modules.users.router import router as users_router

app = FastAPI(
    title="Telemedicina API",
    description="Backend API para la plataforma de Telemedicina",
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

# Registro de routers de módulos
app.include_router(auth_router)
app.include_router(roles_router)
app.include_router(users_router)


@app.get("/", tags=["General"], summary="Health Check")
def health_check():
    """Endpoint de estado del servicio."""
    return {
        "status": "ok",
        "app": "Telemedicina API",
        "version": "1.0.0"
    }
