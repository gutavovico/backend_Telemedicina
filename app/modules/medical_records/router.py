from fastapi import APIRouter
from app.modules.medical_records.laboratory_orders.router import router as laboratory_orders_router
from app.modules.medical_records.clinical_documents.router import (
    router as clinical_documents_router,
    pacientes_doc_router as clinical_documents_pacientes_router,
)
from app.modules.medical_records.prescriptions.router import (
    router as prescriptions_router,
    medicamentos_router,
)
from app.modules.medical_records.triage.router import router as triage_router
from app.modules.medical_records.patient_profile.router import router as patient_profile_router
from app.modules.medical_records.hce.router import router as hce_router
from app.modules.medical_records.fichas.router import router as fichas_router

router = APIRouter()

# CU03 - Gestión de Pacientes y Expediente Base
router.include_router(patient_profile_router)

# CU12 - Consultar Documentos Clinicos y Examenes
router.include_router(clinical_documents_router)
router.include_router(clinical_documents_pacientes_router)

# CU16: Recetas Médicas Digitales
router.include_router(prescriptions_router)
router.include_router(medicamentos_router)

# CU13: Triaje Preliminar AI
router.include_router(triage_router)
router.include_router(triage_router, prefix="/api/v1")

# CU10 - Emitir Solicitudes de Examenes de Laboratorio
router.include_router(laboratory_orders_router)

# CU28 - Historia Clínica Electrónica Dinámica
router.include_router(hce_router)

# CU09 - Fichas Médicas y Expediente Dinámico
router.include_router(fichas_router, prefix="/medical-records/fichas")
router.include_router(fichas_router, prefix="/fichas")
router.include_router(fichas_router, prefix="/api/v1/fichas")




