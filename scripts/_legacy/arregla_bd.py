import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, dbname='telemedicina', user='postgres', password='milkorano5')
cur = conn.cursor()
# Verificar y arreglar estado para todos los usuarios
cur.execute('SELECT id_usuario, estado FROM usuarios')
rows = cur.fetchall()
print('Usuarios antes del arreglo:')
for r in rows:
    print(f'  id={r[0]}, estado={repr(r[1])}')
# Arreglar estado a 'ACTIVO' (texto limpio)
for row in rows:
    uid = row[0]
    estado_raw = row[1]
    if isinstance(estado_raw, bytes):
        estado_limpio = estado_raw.decode('utf-8', errors='replace').strip()
    else:
        estado_limpio = str(estado_raw).strip()
    # Asegurar que sea 'ACTIVO'
    if estado_limpio.upper() == 'ACTIVO':
        cur.execute('UPDATE usuarios SET estado = %s WHERE id_usuario = %s', ('ACTIVO', uid))
conn.commit()
# Verificar
cur.execute('SELECT id_usuario, estado FROM usuarios')
rows = cur.fetchall()
print('Usuarios despues del arreglo:')
for r in rows:
    print(f'  id={r[0]}, estado={repr(r[1])}')
conn.close()
print('Base de datos arreglada exitosamente!')