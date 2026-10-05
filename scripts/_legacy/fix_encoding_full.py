import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, dbname='telemedicina', user='postgres', password='milkorano5')
cur = conn.cursor()
# Convertir el campo estado a texto UTF-8 puro para todos los usuarios
cur.execute("SELECT id_usuario, estado FROM usuarios")
rows = cur.fetchall()
for row in rows:
    uid = row[0]
    estado_raw = row[1]
    # Si es bytes, decodificar; si es str, asegurar que sea UTF-8 limpio
    if isinstance(estado_raw, bytes):
        estado_limpio = estado_raw.decode('utf-8', errors='replace')
    else:
        # Si ya es str, asegurarse que no tenga caracteres extraños
        try:
            estado_limpio = str(estado_raw, 'utf-8')
        except:
            estado_limpio = str(estado_raw)
    cur.execute('UPDATE usuarios SET estado = %s WHERE id_usuario = %s', (estado_limpio, uid))
conn.commit()
# Verificar
cur.execute('SELECT id_usuario, estado FROM usuarios')
all_rows = cur.fetchall()
print('Total usuarios:', len(all_rows))
for r in all_rows:
    print('  id:', r[0], 'estado:', repr(r[1]))
conn.close()
print('¡Arreglo completado!')