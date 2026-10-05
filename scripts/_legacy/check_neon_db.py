import os

import psycopg2
from dotenv import load_dotenv

from app.core.security import hash_password

# La credencial ya no se versiona: se lee de .env (DB_PASSWORD).
load_dotenv()

conn = psycopg2.connect(
    host='ep-steep-shadow-ay9kgisu-pooler.c-5.us-east-2.aws.neon.tech',
    port=5432,
    dbname='Telemedicina',
    user='neondb_owner',
    password=os.environ['DB_PASSWORD']
)
cur = conn.cursor()

cur.execute('SELECT id_clinica, nombre FROM clinicas')
clinicas = cur.fetchall()
print('Clínicas:')
for c in clinicas:
    print(f'  id={c[0]}, nombre={c[1]}')

cur.execute('SELECT id_rol, nombre, id_clinica FROM roles')
roles = cur.fetchall()
print('\nRoles:')
for r in roles:
    print(f'  id={r[0]}, nombre={r[1]}, id_clinica={r[2]}')

cur.execute('SELECT id_usuario, correo, id_rol, id_clinica, estado FROM usuarios')
usuarios = cur.fetchall()
print('\nUsuarios:')
for u in usuarios:
    print(f'  id={u[0]}, correo={u[1]}, id_rol={u[2]}, id_clinica={u[3]}, estado={u[4]}')

cur.execute('SELECT id_paciente, id_usuario, ci, nombres, apellidos, id_clinica FROM pacientes')
pacientes = cur.fetchall()
print('\nPacientes:')
for p in pacientes:
    print(f'  id={p[0]}, id_usuario={p[1]}, ci={p[2]}, nombres={p[3]}, apellidos={p[4]}, id_clinica={p[5]}')

conn.close()