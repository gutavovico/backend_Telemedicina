
import sys
import os
sys.path.append(os.getcwd())
from app.core.database import SessionLocal
from sqlalchemy import text
from app.core.security import hash_password

db = SessionLocal()
new_hash = hash_password('paciente123')
db.execute(text('UPDATE usuarios SET password_hash = :hash WHERE correo = :correo'), {'hash': new_hash, 'correo': 'paciente.test@telemedicina.com'})
db.execute(text('UPDATE usuarios SET password_hash = :hash WHERE correo = :correo2'), {'hash': new_hash, 'correo2': 'paciente@telemedicina.com'})
db.commit()
print('Password updated to paciente123')

