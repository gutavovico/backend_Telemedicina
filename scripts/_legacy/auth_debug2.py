import sys
sys.path.insert(0, '.')
from app.modules.auth.service import get_user_by_email, authenticate_user
from app.core.database import SessionLocal

db = SessionLocal()
try:
    user = get_user_by_email(db=db, correo='admin@telemedicina.com')
    print('=== PASO 1: get_user_by_email ===')
    print('user:', user)
    if user:
        print('user.estado:', repr(user.estado))
        print('type(user.estado):', type(user.estado))
        print('user.estado.lower():', repr(user.estado.lower()))
        print('user.estado.lower() == \"activo\":', user.estado.lower() == 'activo')
    
    print()
    print('=== PASO 2: authenticate_user ===')
    user2 = authenticate_user(db=db, correo='admin@telemedicina.com', password='admin123')
    print('user2:', user2)
    if user2:
        print('user2.estado:', repr(user2.estado))
        print('user2.estado.lower():', repr(user2.estado.lower()))
        print('user2.estado.lower() == \"activo\":', user2.estado.lower() == 'activo')
except Exception as e:
    print('Exception:', type(e).__name__, str(e))
    import traceback
    traceback.print_exc()
finally:
    db.close()