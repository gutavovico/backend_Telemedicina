import sys
sys.path.insert(0, '.')

from app.core.database import SessionLocal
from app.modules.auth.service import authenticate_user
from app.modules.medical_records.clinical_documents.service import list_documents, get_patient_id_by_user
from app.modules.auth.models import Usuario

db = SessionLocal()

# 1. Autenticar usuario
user = authenticate_user(db=db, correo='paciente.test@telemedicina.com', password='paciente123')
print(f'Usuario autenticado: {user.correo} (id={user.id_usuario}, rol={user.id_rol})')

# 2. Verificar paciente vinculado
patient_id = get_patient_id_by_user(db, user.id_usuario)
print(f'Paciente vinculado: id_paciente={patient_id}')

# 3. Probar list_documents (simula GET /api/v1/documentos/me)
items, total, total_pages = list_documents(
    db=db,
    current_user=user,
    tenant_id=1,  # Clinica Central
    page=1,
    page_size=20
)
print(f'Documentos encontrados: {total} (página 1 de {total_pages})')
for d in items:
    print(f'  - id={d.id_documento}, tipo={d.tipo_documento}, titulo={d.titulo}, estado={d.estado}, fecha={d.fecha_documento}')

db.close()