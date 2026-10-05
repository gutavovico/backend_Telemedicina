import os

import bcrypt
from dotenv import load_dotenv

# Fix passlib compatibility with bcrypt >= 4.0.0 (same as app/core/security.py)
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("about", (), {"__version__": getattr(bcrypt, "__version__", "4.0.0")})

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

password = 'paciente123'
password_hash = hash_password(password)
print(f'Password: {password}')
print(f'Hash: {password_hash}')

import psycopg2

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

# 1. Verificar clínica
cur.execute('SELECT id_clinica, nombre FROM clinicas')
clinicas = cur.fetchall()
print('\nClínicas:')
for c in clinicas:
    print(f'  id={c[0]}, nombre={c[1]}')
clinica_id = clinicas[0][0] if clinicas else 1

# 2. Verificar rol PACIENTE
cur.execute("SELECT id_rol FROM roles WHERE nombre = 'PACIENTE'")
rol_paciente = cur.fetchone()
if not rol_paciente:
    print('\nCreando rol PACIENTE...')
    cur.execute("INSERT INTO roles (nombre, descripcion, estado) VALUES ('PACIENTE', 'Paciente', 'ACTIVO') RETURNING id_rol")
    rol_paciente = cur.fetchone()
    conn.commit()
    print(f'Rol PACIENTE creado con id={rol_paciente[0]}')
else:
    print(f'\nRol PACIENTE existente: id={rol_paciente[0]}')
rol_paciente_id = rol_paciente[0]

# 3. Crear usuario PACIENTE
email = 'paciente.test@telemedicina.com'

cur.execute('SELECT id_usuario FROM usuarios WHERE correo = %s', (email,))
existing = cur.fetchone()
if existing:
    print(f'\nUsuario ya existe: id={existing[0]}')
    usuario_id = existing[0]
    # Actualizar password y rol por si acaso
    cur.execute('UPDATE usuarios SET password_hash = %s, id_rol = %s, estado = %s WHERE id_usuario = %s',
                (password_hash, rol_paciente_id, 'ACTIVO', usuario_id))
    conn.commit()
else:
    print('\nCreando usuario PACIENTE...')
    cur.execute('''
        INSERT INTO usuarios (id_clinica, id_rol, nombres, apellidos, correo, telefono, password_hash, foto_perfil, estado, notificaciones_push, notificaciones_email, notificaciones_sms)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id_usuario
    ''', (clinica_id, rol_paciente_id, 'Juan', 'Perez', email, '+591 70000100', password_hash, None, 'ACTIVO', True, True, False))
    usuario_id = cur.fetchone()[0]
    conn.commit()
    print(f'Usuario creado con id={usuario_id}')

# 4. Crear/vincular paciente
ci = '12345678'
cur.execute('SELECT id_paciente FROM pacientes WHERE id_usuario = %s', (usuario_id,))
existing_pac = cur.fetchone()
if existing_pac:
    print(f'\nPaciente ya vinculado: id={existing_pac[0]}')
    paciente_id = existing_pac[0]
else:
    print('\nCreando paciente vinculado...')
    cur.execute('''
        INSERT INTO pacientes (id_clinica, id_usuario, nombres, apellidos, ci, complemento, fecha_nacimiento, genero, telefono, correo, direccion, ciudad, estado)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id_paciente
    ''', (clinica_id, usuario_id, 'Juan', 'Perez', ci, '', '1990-05-15', 'M', '+591 70000100', email, 'Av. Principal 123', 'Santa Cruz', 'ACTIVO'))
    paciente_id = cur.fetchone()[0]
    conn.commit()
    print(f'Paciente creado con id={paciente_id}')

# 5. Verificar
cur.execute('''
    SELECT u.id_usuario, u.correo, u.nombres, u.apellidos, u.id_rol, r.nombre as rol, u.estado,
           p.id_paciente, p.ci, p.nombres, p.apellidos
    FROM usuarios u
    JOIN roles r ON u.id_rol = r.id_rol
    LEFT JOIN pacientes p ON p.id_usuario = u.id_usuario
    WHERE u.correo = %s
''', (email,))
result = cur.fetchone()
print('\n=== USUARIO PACIENTE CREADO ===')
print(f'ID Usuario: {result[0]}')
print(f'Email: {result[1]}')
print(f'Nombre: {result[2]} {result[3]}')
print(f'Rol: {result[5]} (id={result[4]})')
print(f'Estado: {result[6]}')
print(f'ID Paciente: {result[7]}')
print(f'CI: {result[8]}')
print(f'Paciente: {result[9]} {result[10]}')
print(f'\n=== CREDENCIALES PARA PROBAR CU12 EN MÓVIL ===')
print(f'Email: {email}')
print(f'Password: {password}')
print(f'Clínica ID: {clinica_id}')
print(f'Rol: PACIENTE')
print(f'Paciente vinculado: SÍ (id_paciente={paciente_id})')

conn.close()