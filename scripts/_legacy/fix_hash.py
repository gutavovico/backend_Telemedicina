import sys
sys.path.insert(0, '.')
import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='telemedicina', user='postgres', password='milkorano5')
cur = conn.cursor()

# El hash generado por passlib bcrypt
new_hash = '$2b$12$30e0LMlFBJa0Ziav2fLqXu8VbBAle6uSRdnoaYQLbGWn2DESAnDxy'
cur.execute('UPDATE usuarios SET password_hash = %s WHERE correo = %s', (new_hash, 'admin@telemedicina.com'))
conn.commit()

# Verificar
cur.execute('SELECT password_hash FROM usuarios WHERE correo = %s', ('admin@telemedicina.com',))
row = cur.fetchone()
print('Hash en BD:', row[0])

conn.close()