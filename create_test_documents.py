"""Sembrador de documentos clínicos de prueba para CU12.

Uso:
    python create_test_documents.py

Lee la conexión desde el archivo .env de la raíz del backend
(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD). No contiene credenciales.
"""
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

conn = psycopg2.connect(
    host=os.environ["DB_HOST"],
    port=os.environ["DB_PORT"],
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
)
cur = conn.cursor()

# Obtener IDs necesarios
# Paciente
cur.execute("SELECT id_paciente, id_clinica, nombres, apellidos FROM pacientes WHERE id_usuario = (SELECT id_usuario FROM usuarios WHERE correo = 'paciente.test@telemedicina.com')")
paciente = cur.fetchone()
if not paciente:
    print("ERROR: Paciente no encontrado")
    conn.close()
    exit(1)

paciente_id, clinica_id, pac_nombres, pac_apellidos = paciente
print(f'Paciente: {pac_nombres} {pac_apellidos} (id_paciente={paciente_id}, id_clinica={clinica_id})')

# Médico firmante (buscar uno en la misma clínica)
cur.execute("SELECT id_usuario FROM usuarios WHERE id_rol = (SELECT id_rol FROM roles WHERE nombre = 'MEDICO') AND id_clinica = %s LIMIT 1", (clinica_id,))
medico = cur.fetchone()
medico_id = medico[0] if medico else 1
print(f'Médico firmante: id_usuario={medico_id}')

# Hash válido SHA-256 (64 chars) para testing
HASH_OK = "a" * 64

# Documentos a crear
documentos = [
    {
        "tipo_documento": "RECETA",
        "titulo": "Receta Amoxicilina 500mg",
        "descripcion": "Tratamiento para infección respiratoria - 1 capsula cada 8 horas por 7 días",
        "archivo_url": f"documentos/{clinica_id}/receta-amoxicilina-{paciente_id}.pdf",
        "hash_archivo": HASH_OK,
        "fecha_documento": "2026-09-01"
    },
    {
        "tipo_documento": "RECETA",
        "titulo": "Receta Ibuprofeno 400mg",
        "descripcion": "Antiinflamatorio - 1 tableta cada 6 horas por 5 días",
        "archivo_url": f"documentos/{clinica_id}/receta-ibuprofeno-{paciente_id}.pdf",
        "hash_archivo": HASH_OK,
        "fecha_documento": "2026-09-05"
    },
    {
        "tipo_documento": "ORDEN_LAB",
        "titulo": "Orden Hemograma Completo",
        "descripcion": "Control pre-operatorio - Hemograma, Plaquetas, VSG",
        "archivo_url": f"documentos/{clinica_id}/orden-hemograma-{paciente_id}.pdf",
        "hash_archivo": HASH_OK,
        "fecha_documento": "2026-09-10"
    },
    {
        "tipo_documento": "RESULTADO_LAB",
        "titulo": "Resultado Hemograma Completo",
        "descripcion": "Leucocitos: 7.500, Hemoglobina: 14.2, Hematocrito: 42%, Plaquetas: 280.000",
        "archivo_url": f"documentos/{clinica_id}/resultado-hemograma-{paciente_id}.pdf",
        "hash_archivo": HASH_OK,
        "fecha_documento": "2026-09-12"
    },
    {
        "tipo_documento": "CERTIFICADO",
        "titulo": "Certificado Médico Laboral",
        "descripcion": "Apto para actividades laborales sin restricciones",
        "archivo_url": f"documentos/{clinica_id}/certificado-laboral-{paciente_id}.pdf",
        "hash_archivo": HASH_OK,
        "fecha_documento": "2026-09-15"
    },
    {
        "tipo_documento": "INDICACION",
        "titulo": "Indicaciones Post-Consulta",
        "descripcion": "Reposo relativo 48h, hidratación abundante, control en 7 días",
        "archivo_url": f"documentos/{clinica_id}/indicaciones-postconsulta-{paciente_id}.pdf",
        "hash_archivo": HASH_OK,
        "fecha_documento": "2026-09-15"
    }
]

print(f'\nCreando {len(documentos)} documentos...')

for i, doc in enumerate(documentos, 1):
    cur.execute('''
        INSERT INTO documentos_clinicos (id_clinica, id_paciente, id_cita, tipo_documento, titulo, descripcion, archivo_url, hash_archivo, firmado_por, fecha_documento, metadatos, estado)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id_documento
    ''', (
        clinica_id,
        paciente_id,
        None,  # id_cita
        doc["tipo_documento"],
        doc["titulo"],
        doc["descripcion"],
        doc["archivo_url"],
        doc["hash_archivo"],
        medico_id,
        doc["fecha_documento"],
        None,  # metadatos
        "ACTIVO"
    ))
    doc_id = cur.fetchone()[0]
    conn.commit()
    print(f'  {i}. {doc["tipo_documento"]}: {doc["titulo"]} (id={doc_id})')

# Verificar
cur.execute('''
    SELECT id_documento, tipo_documento, titulo, fecha_documento, estado
    FROM documentos_clinicos
    WHERE id_paciente = %s
    ORDER BY fecha_documento DESC, id_documento DESC
''', (paciente_id,))

docs_creados = cur.fetchall()
print(f'\n=== DOCUMENTOS CREADOS PARA PACIENTE {paciente_id} ===')
for d in docs_creados:
    print(f'  id={d[0]} | {d[1]} | {d[2]} | {d[3]} | {d[4]}')

print(f'\nTotal: {len(docs_creados)} documentos')
print(f'\n✅ Listo para probar CU12 en móvil con:')
print(f'   Email: paciente.test@telemedicina.com')
print(f'   Password: paciente123')

conn.close()