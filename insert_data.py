import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, dbname='telemedicina', user='postgres', password='milkorano5')
cur = conn.cursor()

# 1. Crear clínica
cur.execute("INSERT INTO clinicas (nombre, estado) VALUES (%s, %s) RETURNING id_clinica", ('Hospital San Juan de Dios', 'ACTIVO'))
clinic_id = cur.fetchone()[0]
print('Clínica creada con ID:', clinic_id)

# 2. Insertar usuarios con el ID de clínica y roles globales (id_clinica NOT NULL, id_rol según el DDL)
# Rol 1: Administracion, Rol 2: Médico
password_hash_1 = '$2b$12$dummy_hash_1'
password_hash_2 = '$2b$12$dummy_hash_2'

cur.execute("""
    INSERT INTO usuarios (id_clinica, id_rol, nombres, apellidos, correo, telefono, password_hash, foto_perfil, estado, notificaciones_push, notificaciones_email, notificaciones_sms)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", (clinic_id, 1, 'Admin', 'Sistema', 'admin@telemedicina.com', '+591 70000000', password_hash_1, None, 'ACTIVO', True, True, False))

cur.execute("""
    INSERT INTO usuarios (id_clinica, id_rol, nombres, apellidos, correo, telefono, password_hash, foto_perfil, estado, notificaciones_push, notificaciones_email, notificaciones_sms)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", (clinic_id, 2, 'Doctor', 'Prueba', 'doctor@telemedicina.com', '+591 71111111', password_hash_2, None, 'ACTIVO', True, True, False))

conn.commit()
cur.execute('SELECT * FROM usuarios')
rows = cur.fetchall()
print('Usuarios insertados:', len(rows))
for r in rows:
    print(' -', r)

conn.close()
print('¡Éxito!')