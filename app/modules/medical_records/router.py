from fastapi import APIRouter
from app.modules.medical_records.laboratory_orders.router import router as laboratory_orders_router
from app.modules.medical_records.clinical_documents.router import (
    router as clinical_documents_router,
    pacientes_doc_router as clinical_documents_pacientes_router,
)

router = APIRouter()

# CU12 - Consultar Documentos Clinicos y Examenes
router.include_router(clinical_documents_router)
router.include_router(clinical_documents_pacientes_router)

# CU10 - Emitir Solicitudes de Examenes de Laboratorio
router.include_router(laboratory_orders_router)