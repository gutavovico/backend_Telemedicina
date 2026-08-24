import sys
import os
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), ".")))

import psycopg2
from app.core.security import hash_password

# Hashes generados: recep123 y paciente123
recep_hash = '$2b$12$XIMXjdhmLCRhX7vAJKvjZeNG1QpI9x2mJNnDEv5ox3y59Cte4Fg4m'
patient_hash = '$2b$12$EXC5/LSd3pcoaFUebeNxYesuv6XwfcNls.IgX6qh/2SaHWZPsUaY2'

conn = psycopg2.connect(host='localhost', port=5432, dbname='telemedicina', user='postgres', password='milkorano5')
cur = conn.cursor()

# 1. Insertar usuario de Recepción (id_rol=3)
cur.execute("""
    INSERT INTO usuarios (id_clinica, id_rol, nombres, apellidos, correo, telefono, password_hash, foto_perfil, estado, notificaciones_push, notificaciones_email, notificaciones_sms)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", (1, 3, 'Recepcionista', 'Principal', 'recep@telemedicina.com', '+591 70000000', recep_hash, None, 'ACTIVO', True, True, False))

# 2. Insertar usuario de Paciente (id_rol=4)
cur.execute("""
    INSERT INTO usuarios (id_clinica, id_rol, nombres, apellidos, correo, telefono, password_hash, foto_perfil, estado, notificaciones_push, notificaciones_email, notificaciones_sms)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", (1, 4, 'Paciente', 'Ejemplo', 'paciente@telemedicina.com', '+591 71111111', patient_hash, None, 'ACTIVO', True, True, False))

conn.commit()

# Verificar
cur.execute("SELECT id_usuario, nombres, apellidos, correo, id_rol FROM usuarios ORDER BY id_usuario")
rows = cur.fetchall()
print('Usuarios en BD:')
for r in rows:
    print(' -', r)

conn.close()
print('¡Éxito! Se insertaron los nuevos usuarios con roles Recepción y Paciente.')