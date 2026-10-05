import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, dbname='telemedicina', user='postgres', password='milkorano5')
cur = conn.cursor()
cur.execute('SELECT id_usuario, nombres, correo, estado FROM usuarios ORDER BY id_usuario')
rows = cur.fetchall()
print('Usuarios en BD:')
for r in rows:
    print(f'  id={r[0]}, nombres={r[1]}, correo={r[2]}, estado={repr(r[3])}')
cur.execute('SELECT * FROM roles')
rows = cur.fetchall()
print('\\nRoles en BD:')
for r in rows:
    print(f'  id={r[0]}, nombre={r[1]}, id_clinica={r[2]}')
conn.close()