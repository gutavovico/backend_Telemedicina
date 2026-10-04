from fastapi import APIRouter
from app.modules.appointments.doctor_profile.router import (
    router as doctor_profile_router,
    router_especialidades,
)
from app.modules.appointments.agenda.router import router as agenda_router
from app.modules.appointments.consultas.router import router as consultas_router

router = APIRouter()

# 1. Rutas principales de Médicos (/medicos y /appointments/medicos)
router.include_router(doctor_profile_router)
router.include_router(doctor_profile_router, prefix="/appointments")

# 2. Rutas del Catálogo de Especialidades (/especialidades y /appointments/especialidades)
router.include_router(router_especialidades)
router.include_router(router_especialidades, prefix="/appointments")

# 3. Rutas de Agenda Médica (CU05)
router.include_router(agenda_router)

# 4. Rutas de Consultas y Citas Médicas (CU25)
router.include_router(consultas_router, prefix="/appointments/consultas")
router.include_router(consultas_router, prefix="/citas")
router.include_router(consultas_router, prefix="/appointments/citas")


