from fastapi import APIRouter
from app.modules.medical_records.patient_profile.router import router as patient_profile_router
from app.modules.medical_records.clinical_documents.router import (
    pacientes_doc_router as clinical_documents_pacientes_router,
)
from app.modules.medical_records.clinical_documents.router import router as clinical_documents_router

router = APIRouter()

# Incluir casos de uso de historias clínicas y pacientes
router.include_router(patient_profile_router)

# CU12 - Consultar Documentos Clínicos y Exámenes
router.include_router(clinical_documents_router)
router.include_router(clinical_documents_pacientes_router)
