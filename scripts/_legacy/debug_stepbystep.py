import sys
sys.path.insert(0, '.')
from app.modules.auth.service import authenticate_user, get_user_by_email
from app.core.database import SessionLocal

db = SessionLocal()
try:
    # Paso 1: Obtener usuario
    user = get_user_by_email(db=db, correo='admin@telemedicina.com')
    print('Paso 1 - Usuario obtenido:', user)
    if user:
        print('Paso 1 - user.estado:', repr(user.estado))
        print('Paso 1 - user.estado.lower():', repr(user.estado.lower()))
    
    # Paso 2: Autenticar
    user2 = authenticate_user(db=db, correo='admin@telemedicina.com', password='admin123')
    print('Paso 2 - User authenticated:', user2)
    if user2:
        print('Paso 2 - user2.estado:', repr(user2.estado))
        print('Paso 2 - user2.estado.lower():', repr(user2.estado.lower()))
        print('Paso 2 - Comparison result:', user2.estado.lower() != 'activo')
except Exception as e:
    print('Exception:', type(e).__name__, str(e))
    import traceback
    traceback.print_exc()
finally:
    db.close()