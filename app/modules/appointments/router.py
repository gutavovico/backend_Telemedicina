from fastapi import APIRouter
from app.modules.appointments.doctor_profile.router import (
    router as doctor_profile_router,
    router_especialidades,
)
from app.modules.appointments.agenda.router import router as agenda_router
from app.modules.appointments.consultas.router import router as consultas_router
from app.modules.appointments.live_queue.router import router as live_queue_router

router = APIRouter()

# 1. Rutas principales de Médicos (/medicos, /appointments/medicos y /api/v1/medicos)
router.include_router(doctor_profile_router)
router.include_router(doctor_profile_router, prefix="/appointments")
router.include_router(doctor_profile_router, prefix="/api/v1")

# 2. Rutas del Catálogo de Especialidades (/especialidades, /appointments/especialidades y /api/v1/especialidades)
router.include_router(router_especialidades)
router.include_router(router_especialidades, prefix="/appointments")
router.include_router(router_especialidades, prefix="/api/v1")

# 3. Rutas de Agenda Médica (CU05)
router.include_router(agenda_router)
router.include_router(agenda_router, prefix="/api/v1")

# 3b. Fila virtual y tiempos de espera (CU08): /cola y /api/v1/cola
router.include_router(live_queue_router)
router.include_router(live_queue_router, prefix="/api/v1")

# 4. Rutas de Consultas y Citas Médicas (CU25)
router.include_router(consultas_router, prefix="/appointments/consultas")
router.include_router(consultas_router, prefix="/citas")
router.include_router(consultas_router, prefix="/appointments/citas")
router.include_router(consultas_router, prefix="/api/v1/citas")



