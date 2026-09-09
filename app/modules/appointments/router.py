from fastapi import APIRouter
from app.modules.appointments.doctor_profile.router import (
    router as doctor_profile_router,
    router_especialidades,
)
from app.modules.appointments.medical_agenda.router import router as medical_agenda_router

router = APIRouter()

# 1. Rutas principales de Médicos (/medicos y /appointments/medicos)
router.include_router(doctor_profile_router)
router.include_router(doctor_profile_router, prefix="/appointments")

# 2. Rutas del Catálogo de Especialidades (/especialidades y /appointments/especialidades)
router.include_router(router_especialidades)
router.include_router(router_especialidades, prefix="/appointments")

# CU05 conserva un único prefijo /appointments/agenda.
router.include_router(medical_agenda_router)
