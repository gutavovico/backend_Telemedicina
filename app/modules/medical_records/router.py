from fastapi import APIRouter
from app.modules.medical_records.patient_profile.router import router as patient_profile_router

router = APIRouter()

# Incluir casos de uso de historias clínicas y pacientes
router.include_router(patient_profile_router)
