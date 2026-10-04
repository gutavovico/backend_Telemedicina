import sys
sys.path.insert(0, '.')
from app.modules.auth.service import authenticate_user
from app.core.database import SessionLocal

db = SessionLocal()
try:
    user = authenticate_user(db=db, correo='admin@telemedicina.com', password='admin123')
    print('User:', user)
    if user:
        print('estado:', repr(user.estado))
        print('estado.lower():', repr(user.estado.lower()))
        print('comparison user.estado.lower() != "activo":', user.estado.lower() != 'activo')
except Exception as e:
    print('Exception:', type(e).__name__, str(e))
    import traceback
    traceback.print_exc()
finally:
    db.close()