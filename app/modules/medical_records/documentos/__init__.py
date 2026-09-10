from app.modules.medical_records.clinical_documents.models import DocumentoClinico
from app.modules.medical_records.clinical_documents.router import router, pacientes_doc_router
from app.modules.medical_records.clinical_documents import schemas, service, storage, dependencies

__all__ = [
    "DocumentoClinico",
    "router",
    "pacientes_doc_router",
    "schemas",
    "service",
    "storage",
    "dependencies",
]
