import os

import bcrypt
from dotenv import load_dotenv

# Fix passlib compatibility with bcrypt >= 4.0.0
if not hasattr(bcrypt, '__about__'):
    class About:
        __version__ = getattr(bcrypt, '__version__', '3.2.0')
    bcrypt.__about__ = About()

from passlib.context import CryptContext
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')

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

email = 'paciente.test@telemedicina.com'
password = 'paciente123'
password_hash = pwd_context.hash(password)

cur.execute('UPDATE usuarios SET password_hash = %s WHERE correo = %s', (password_hash, email))
conn.commit()
print(f'Password actualizado para {email}')
print(f'Hash: {password_hash}')

# Verify
cur.execute('SELECT password_hash FROM usuarios WHERE correo = %s', (email,))
result = cur.fetchone()
print(f'Hash en BD: {result[0]}')

# Test verify
verified = pwd_context.verify(password, result[0])
print(f'Verificación: {verified}')

conn.close()