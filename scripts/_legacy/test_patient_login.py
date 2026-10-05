import sys
sys.path.insert(0, '.')
from app.modules.auth.service import authenticate_user
from app.core.database import SessionLocal

db = SessionLocal()
user = authenticate_user(db=db, correo='paciente.test@telemedicina.com', password='paciente123')
print('Resultado authenticate_user:', user)
if user:
    print('user.id_usuario:', user.id_usuario)
    print('user.correo:', user.correo)
    print('user.nombres:', user.nombres)
    print('user.apellidos:', user.apellidos)
    print('user.id_rol:', user.id_rol)
    print('user.estado:', user.estado)
    print('user.estado.lower():', user.estado.lower())
    print('Es PACIENTE:', user.id_rol == 4)
else:
    print('ERROR: Usuario no autenticado')
db.close()