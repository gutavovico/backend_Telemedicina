# `_legacy/` — restos archivados

Esta carpeta **no es código de producción**. No se importa desde ningún router ni
desde `app/main.py`. Guarda restos de casos de uso que quedaron a medio
implementar y que **bloqueaban el arranque del backend**.

Nada aquí se ejecuta. Se conserva para no perder trabajo si alguien retoma el
caso de uso correspondiente.

---

## `patient_profile/`

**Caso de uso:** CU03 — Gestión de Pacientes (perfil del paciente). **No es parte
de CU10, CU12 ni CU23.**

**Estado:** el código fuente `.py` fue borrado del repositorio. Solo sobreviven
los bytecode compilados en `__pycache__/`, que Python no puede importar porque
no existe el `.py` padre. Esto rompía el arranque de todo el dominio:

```
app/modules/medical_records/router.py:2
    from app.modules.medical_records.patient_profile.router import router as patient_profile_router

ModuleNotFoundError: No module named 'app.modules.medical_records.patient_profile.router'
```

Como `main.py` importa `medical_records.router` de forma transitiva, el
bloqueo impedía montar **cualquier** router del dominio, incluidos los de CU12.

### Qué contiene el bytecode archivado

| Archivo | Tamaño | Contenido recuperable |
|---|---:|---|
| `router.cpython-312.pyc` | 8 166 B | Endpoints del perfil de paciente |
| `schemas.cpython-312.pyc` | 9 118 B | Esquemas Pydantic del perfil |
| `service.cpython-312.pyc` | 10 137 B | Lógica de negocio del perfil |
| `__init__.cpython-312.pyc` | 204 B | Marcador de paquete |

### Cómo recuperarlo

Los `.pyc` son descompilables (Python 3.12) con herramientas como `decompyle3`
o `uncompyle6`, pero la recuperación es parcial y manual. El enfoque
recomendado si se retoma CU03 es reimplementar desde el contrato:

```
openspec/contracts/patients.md
openspec/specs/patient-management/spec.md
```

**Endpoints que la interfaz de CU12 esperaba de este módulo** (y que hoy no
existen, sin pérdida para CU12 porque CU12 expone su propio endpoint):

- `GET /api/v1/pacientes` — listado
- `GET /api/v1/pacientes/{id}` — detalle
- `PUT /api/v1/pacientes/{id}` — actualización
