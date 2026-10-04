import sys
sys.path.insert(0, '.')
from app.core.security import verify_password
import psycopg2

conn = psycopg2.connect(host='localhost',port=5432,dbname='telemedicina',user='postgres',password='milkorano5')
cur = conn.cursor()
cur.execute('SELECT password_hash, estado FROM usuarios WHERE correo = %s', ('admin@telemedicina.com',))
row = cur.fetchone()
print('password_hash:', row[0])
print('estado:', row[1])

# Verificar password
pw_result = verify_password('admin123', row[0])
print('Verify password result:', pw_result)

# Verificar estado con lower
estado_lower = row[1].lower()
print('estado.lower():', repr(estado_lower))
print('estado.lower() != \"activo\":', estado_lower != 'activo')

conn.close()