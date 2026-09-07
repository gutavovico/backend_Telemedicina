from fastapi import APIRouter
from app.modules.appointments.doctor_profile.router import (
    router as doctor_profile_router,
    router_especialidades,
)
from app.modules.appointments.citas_router import citas_router

router = APIRouter()

# 1. Rutas principales de Médicos (/medicos y /appointments/medicos)
router.include_router(doctor_profile_router)
router.include_router(doctor_profile_router, prefix="/appointments")

# 2. Rutas del Catálogo de Especialidades (/especialidades y /appointments/especialidades)
router.include_router(router_especialidades)
router.include_router(router_especialidades, prefix="/appointments")

# 3. Rutas de Consultas y Citas Médicas (/citas y /appointments/citas)
router.include_router(citas_router)
router.include_router(citas_router, prefix="/appointments")

