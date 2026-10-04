# `_legacy/bytecode/` — bytecode huérfano

Contiene los archivos `.pyc` compilation de fuentes `.py` que fueron borrados
del repositorio. Se movieron aquí el 2026-10-02 durante el saneamiento previo
a rehacer CU10, CU12 y CU23.

## Por qué existían

Python escribe un `.pyc` en `__pycache__/` cada vez que importa un módulo. Si
después alguien borra el `.py` sin limpiar `__pycache__/`, el bytecode queda
huérfano. Aquí no es inofensivo: fue la causa de dos fallos que bloqueaban el
arranque del backend.

## Qué rompían

**1. Módulos sin fuente no importables.** `medical_records/router.py:2`
importaba `medical_records.patient_profile.router`. El `.py` ya no existía, y
un `.pyc` suelto en `__pycache__/` **no** es importable por Python (exige el
`.py`). Resultado:

```
ModuleNotFoundError: No module named 'app.modules.medical_records.patient_profile.router'
```

Como ese import ocurre al montar `medical_records`, **ningún** router del
dominio podía cargarse, incluidos los 8 endpoints de CU12.

**2. Cadena de migraciones rota.** `003_crear_tabla_citas.py` declara
`down_revision = 'e9b1a6ac1592'`, pero la revisión merge que tenía ese id fue
borrada. Alembic construye el mapa de revisiones leyendo todos los `.py` de
`versions/`, así que rompía en tiempo de ejecución:

```
KeyError: 'e9b1a6ac1592'
alembic/script/revision.py:240, in _revision_map
    down_revision = map_[downrev]
```

`alembic upgrade head` era imposible.

## Contenido

52 archivos, listados en `MANIFEST.txt`. Los de mayor interés:

### `alembic/versions/` — 4 migraciones perdidas

Recuperables: el bytecode conserva los docstrings y las cadenas de cada
`upgrade()` / `downgrade()`.

| Revisión perdida | Qué creaba |
|---|---|
| `002_crear_tabla_pacientes` | Tabla `pacientes` con 25 columnas. **Imprescindible**: la migración `004_crear_documentos_clinicos` ejecuta `ALTER TABLE pacientes ADD COLUMN id_clinica`, así que la tabla debe existir. |
| `002_agregar_version_sesion` | Columna `usuarios.token_version` |
| `002_crear_medicos_especialidades` | Tablas `especialidades`, `medicos`, `medico_especialidad` |
| `e9b1a6ac1592_merge_all_branches` | Revisión merge sin cuerpo (`upgrade()` vacío) que unificaba las ramas anteriores |

### `app/modules/auth/` — refactor abandonado (CU01 / CU23 / CU24)

`login/`, `logout/`, `password_recovery/`, `roles_permissions/`,
`users_management/`. Sus `.py` se borraron al consolidar todo en
`app/modules/auth/router.py`. De `password_recovery/` (CU23) se conserva la
versión alternativa con `ForgotPasswordResponse`, `ResetPasswordRequest` y
validación por regex `^[0-9]{6}$`.

### `tests/` — suites perdidas

`test_cu02_users` (CU02) y `test_cu26_roles_permissions` (CU26).

## Cómo revertir el movimiento

Para devolver un archivo a su sitio original, copie la ruta que aparece en
`MANIFEST.txt` desde `_legacy/bytecode/<repo>/...` hacia la raíz del
repositorio, usando el sufijo `.cpython-312` que le corresponda (`.pyc` normal,
o `.cpython-312-pytest-9.1.1.pyc` para las suites de pytest).
