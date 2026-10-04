# `scripts/_legacy/` — utilidades de depuración retiradas

Scripts de diagnóstico y corrección manual que estaban sueltos en la raíz del
backend. Se movieron aquí durante el saneamiento del 2026-10-02, antes de
rehacer CU10, CU12 y CU23.

**No son parte de la aplicación.** No los importa ningún módulo de `app/` y
ningún test. Se ejecutaban a mano contra la base de datos de desarrollo.

| Script | Para qué servía |
|---|---|
| `arregla_bd.py` | Correcciones puntuales sobre el esquema |
| `auth_debug2.py` | Depuración del flujo de autenticación |
| `auth_test.py` | Prueba manual de login |
| `check_neon_db.py` | Comprobaba conectividad con Neon |
| `create_patient_user.py` | Daba de alta usuarios paciente |
| `debug_manual.py` | Volcado de estado para diagnóstico |
| `debug_state.py` | Volcado de estado para diagnóstico |
| `debug_stepbystep.py` | Depuración paso a paso |
| `fix_encoding.py` | Reparaba la codificación de archivos |
| `fix_encoding_full.py` | Variante de la anterior, más agresiva |
| `fix_hash.py` | Recalculaba hashes de contraseña |
| `test_patient_documents.py` | Acceso directo al service de documentos |
| `test_patient_login.py` | Login manual de paciente |
| `update_patient_password.py` | Cambiaba contraseñas de prueba |
| `verify_bd.py` | Verificación del estado de la BD |
| `verify_pwd.py` | Verificación de hashes |

## Credenciales

Cuatro de estos scripts tenían el DSN de Neon **con contraseña en texto plano**
(`check_neon_db.py`, `create_patient_user.py`, `update_patient_password.py` y
`create_test_documents.py`). Ninguno estaba versionado por git, así que la
contraseña nunca llegó al remoto, pero conviene rotarla si sigue activa.

`create_test_documents.py` sí se conservó fuera de esta carpeta porque es útil
para verificar CU12; se saneó para leer la conexión desde `.env`.
