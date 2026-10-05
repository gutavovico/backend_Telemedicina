import sys
sys.path.insert(0, '.')
from app.modules.auth.service import authenticate_user
from app.core.database import SessionLocal

db = SessionLocal()
user = authenticate_user(db=db, correo='admin@telemedicina.com', password='admin123')
print('Resultado authenticate_user:', user)
if user:
    print('user.estado:', repr(user.estado))
    print('user.estado.lower():', repr(user.estado.lower()))
    print('user.estado.lower() != \"activo\":', user.estado.lower() != 'activo')
db.close()