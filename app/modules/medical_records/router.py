from fastapi import APIRouter
from app.modules.medical_records.patient_profile.router import router as patient_profile_router
from app.modules.medical_records.hce.router import router as hce_router
from app.modules.medical_records.fichas.router import router as fichas_router
from app.modules.medical_records.clinical_documents.router import (
    router as clinical_documents_router,
    pacientes_doc_router,
)

router = APIRouter()

# Incluir casos de uso de historias clínicas, pacientes y fichas médicas
router.include_router(patient_profile_router)
router.include_router(hce_router)
router.include_router(fichas_router, prefix="/medical-records/fichas")
router.include_router(fichas_router, prefix="/fichas")

# CU12: Documentos Clínicos y Exámenes
router.include_router(clinical_documents_router)
router.include_router(pacientes_doc_router)


