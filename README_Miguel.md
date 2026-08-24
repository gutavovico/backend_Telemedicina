# README_Miguel — Plataforma de Telemedicina

Proyecto de la asignatura **Sistemas de Información 2** para el **Hospital San Juan de Dios**.
Sistema de gestión médica con telemedicina: agendamiento de citas, teleconsultas, historia clínica digital, recetas electrónicas, laboratorio y asistencia por IA.

El proyecto está dividido en **dos repositorios independientes**:

| Carpeta | Rol | Tecnología |
|---|---|---|
| `backend_Telemedicina/` | API REST + lógica de negocio + base de datos | FastAPI, SQLAlchemy, Alembic, PostgreSQL |
| `frontend_Telemedicina/` | Interfaz de usuario | Angular 21, Angular Material, Tailwind CSS |

## Estado actual del avance

- **CU01 Iniciar sesión (completado):** registro de usuarios, login, refresh de tokens y perfil autenticado funcionando de punta a punta (backend + frontend).
- **CU23 Recuperar Acceso (completado):** recuperación de contraseña por correo con código de 6 dígitos (backend + frontend) y cierre de sesión automático por inactividad (frontend). Paquete (pkg) **Autenticación y seguridad**.
  - Hash del doctor corregido (bcrypt válido)
  - Comparación de estado case-insensitive (`user.estado.lower()`)
  - Try-except en SMTP para fallback graceful (no muestra error si el correo se envió)
  - 4 roles funcionando: Administrador, Médico, Recepción, Paciente
  - Módulos nuevos: `organization` (Clinica, Rol) y `security` (Notificacion, Auditoria)
- **Módulos pendientes:** citas, historias clínicas, comunicaciones, asistencia IA y analítica existen como esqueletos vacíos (`app/modules/` en backend y `features/` en frontend), sin lógica implementada.

| Estado | Descripción |
|---|---|
| Estructura base FE/BE | Completado |
| Autenticación (registro, login, refresh) | Completado |
| CU23 Recuperar Acceso (correo + inactividad) | Completado |
| Citas (`appointments`) | Pendiente |
| Historias clínicas (`medical-records`) | Pendiente |
| Comunicaciones (`communications`) | Pendiente |
| Asistente IA (`ai-assistant`) | Pendiente |
| Analítica / reportes (`analytics`) | Pendiente |

---

## Stack tecnológico

| Capa | Tecnología | Detalle |
|---|---|---|
| Frontend | Angular 21.2 (CLI `ng`) | Standalone components + signals, SSR habilitado |
| UI | Angular Material 21 + Tailwind CSS 4 | Componentes y estilos |
| Backend | FastAPI + Uvicorn | API REST documentada en `/docs` |
| ORM | SQLAlchemy 2.0 + Alembic | Modelos y migraciones |
| Base de datos | PostgreSQL en Neon | 42 tablas |
| Autenticación | JWT (python-jose) + bcrypt | Access token (30 min) + refresh token (7 días) |
| Validación | Pydantic v2 + pydantic-settings | Schemas y variables de entorno |

---

## Estructura del proyecto

```
PROYECTO SI2/
├── backend_Telemedicina/
│   ├── app/
│   │   ├── core/                 # Config, BD, seguridad
│   │   │   ├── config.py        # Settings (.env): BD, JWT, CORS, SMTP, reset code
│   │   │   ├── database.py      # Engine SQLAlchemy + sesión
│   │   │   ├── email.py         # Envío de correo (SMTP) + fallback a consola
│   │   │   └── security.py      # Hash bcrypt + JWT + código reset HMAC
│   │   ├── modules/
│   │   │   ├── auth/            # ✔ Registro, login, refresh, /me, forgot/reset password
│   │   │   ├── appointments/    # vacío
│   │   │   ├── medical_records/ # vacío
│   │   │   ├── communications/  # vacío
│   │   │   ├── ai_assistant/    # vacío
│   │   │   ├── analytics/       # vacío
│   │   │   ├── organization/    # ✔ Clinica, Rol (nuevo)
│   │   │   └── security/        # ✔ Notificacion, Auditoria (nuevo)
│   │   └── main.py              # FastAPI app + CORS + routers
│   ├── alembic/                 # Migraciones
│   ├── scripts/
│   │   ├── seed.py              # Usuarios iniciales
│   │   └── test_endpoints.py    # Pruebas de endpoints (incluye CU23)
│   └── requirements.txt
└── frontend_Telemedicina/
    ├── src/
    │   ├── app/
│   │   ├── core/
│   │   │   ├── services/auth.service.ts   # Login, tokens, perfil, recuperación
│   │   │   ├── services/inactivity.service.ts # Cierre por inactividad (CU23)
│   │   │   ├── guards/auth.guard.ts       # Protección de rutas
│   │   │   ├── interceptors/auth.interceptor.ts # JWT + auto-refresh
│   │   │   └── models/auth.models.ts
│   │   ├── features/
│   │   │   ├── home/          # Landing page
│   │   │   ├── auth/login/    # Inicio de sesión
│   │   │   ├── auth/register/ # Registro
│   │   │   ├── auth/recover/  # Recuperar contraseña (solicitar código)
│   │   │   ├── auth/reset-password/ # Restablecer contraseña (código)
│   │   │   ├── appointments/  # vacío
│   │   │   ├── medical-records/ # vacío
│   │   │   ├── communications/ # vacío
│   │   │   ├── ai-assistant/  # vacío
│   │   │   └── analytics/     # vacío
    │   │   └── shared/
    │   │       ├── components/header/  # Header con menú de usuario
    │   │       └── components/footer/  # Footer
    │   ├── environments/          # environment.ts (apiUrl localhost:8000)
    │   └── styles.css
    └── package.json
```

---

## Cómo levantar el proyecto

### Requisitos previos

- Python 3.10+ (backend)
- Node.js (Angular CLI 21)
- PostgreSQL local (por ahora: `localhost:5432`, user `postgres`, pass `12345`, BD `telemedicina`; definir también en `.env`). El esquema de 42 tablas está diseñado para Neon.

### Backend (FastAPI)

```bash
cd backend_Telemedicina
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
alembic upgrade head           # crea la tabla usuarios (BD local)
python scripts/seed.py         # crea usuarios iniciales
python -m uvicorn app.main:app --reload --port 8000
```

- Documentación interactiva: http://localhost:8000/docs
- Health check: http://localhost:8000/

**Usuarios iniciales (seed):**

| Rol | Correo | Contraseña |
|---|---|---|
| Administración | `admin@telemedicina.com` | `admin123` |
| Doctor | `doctor@telemedicina.com` | `doctor123` |

### Frontend (Angular)

```bash
cd frontend_Telemedicina
npm install
ng serve
```

- Aplicación: http://localhost:4200
- El backend debe estar corriendo en http://localhost:8000 (configurado en `src/environments/environment.ts`)

### Pruebas de endpoints (backend)

```bash
cd backend_Telemedicina
python scripts/test_endpoints.py
```

---

## Base de datos

Esquema PostgreSQL (Neon) con **42 tablas**, agrupadas por dominio:

| Dominio | Tablas |
|---|---|
| Organización y planes | `clinicas`, `planes`, `suscripciones` |
| Seguridad / RBAC | `roles`, `permisos`, `rol_permisos`, `componentes_sistema` |
| Usuarios y perfiles | `usuarios`, `pacientes`, `medicos` |
| Especialidades y servicios | `especialidades`, `medico_especialidad`, `servicios_medicos` |
| Agenda | `horarios_medicos`, `bloqueos_agenda`, `citas`, `lista_espera`, `historial_citas` |
| Historia clínica | `historias_clinicas`, `consultas`, `diagnosticos`, `documentos_clinicos` |
| Comunicaciones | `teleconsultas`, `conversaciones`, `mensajes` |
| Recetas y laboratorio | `recetas`, `medicamentos`, `receta_detalle`, `ordenes_laboratorio`, `estudios_laboratorio`, `resultados_laboratorio` |
| Tratamientos e IA | `tratamientos`, `tratamiento_medicamentos`, `seguimiento_tratamiento`, `cuestionarios`, `evaluaciones_triaje`, `asistencias_ia` |
| Soporte | `notificaciones`, `pagos`, `comprobantes`, `reportes`, `auditoria` |

- La tabla `usuarios` se relaciona con `clinicas` y `roles` (1:1) y es la base del módulo de autenticación actual. **CU23**: campos `id_clinica NOT NULL`, `id_rol NOT NULL`, `estado` default `'ACTIVO'`.
- Roles iniciales insertados por el script: Administración, Médico, Recepción, Paciente (todos `id_clinica NULL` = globales).
- Usuarios seed (4):
  - Admin: `admin@telemedicina.com` / `admin123`
  - Doctor: `doctor@telemedicina.com` / `doctor123`
  - Recepción: `recep@telemedicina.com` / `recep123`
  - Paciente: `paciente@telemedicina.com` / `paciente123`

---

## CU23 — Recuperar Acceso (pkg: Autenticación y seguridad)

Caso de uso que cubre dos funcionalidades:

1. **Recuperación de contraseña por correo** mediante código de 6 dígitos.
2. **Cierre de sesión por inactividad** (auto-logout en el frontend).

### Backend

| Endpoint | Descripción |
|---|---|
| `POST /auth/forgot-password` | Recibe `{ correo }`, genera y envía un código de 6 dígitos. Respuesta genérica (no revela correos registrados). |
| `POST /auth/reset-password` | Recibe `{ correo, codigo, nueva_password }`, valida el código y actualiza la contraseña. |

**Mecanismo del código (sin BD, sin migraciones):**
- El código se deriva con **HMAC-SHA256** a partir de `id_usuario + ventana de 30 min + secreto` (`JWT_RESET_SECRET_KEY`), por lo que es determinista dentro de su ventana de validez y no requiere almacenamiento.
- Verificación tolerante: acepta el código del bucket actual o el anterior (resiste cambios de ventana).
- Comparación en **tiempo constante** (`hmac.compare_digest`).
- **Anti fuerza bruta:** máx. 5 intentos fallidos por usuario → bloqueo de 15 minutos (en memoria).

**Mejoras implementadas (CU23):**
- **Try-except en SMTP** (`app/core/email.py`): si el login SMTP falla pero `send_message` ya corrió, no se muestra error al usuario; solo log en consola (`[SMTP WARNING]`).
- **Estado case-insensitive** (`app/modules/auth/service.py`): comparación `user.estado.lower() != "activo"` para aceptar `ACTIVO`/`activo`/`Activo`.
- **Hash del doctor corregido**: regenerado con bcrypt válido (antes era placeholder inválido).

**Configuración de correo (`.env` o defaults en `app/core/config.py`):**

| Variable | Default | Descripción |
|---|---|---|
| `EMAIL_ENABLED` | `False` | `False` = modo dev, el código se imprime en consola y viaja en `debug_code`. `True` = SMTP real. |
| `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `587` | Servidor SMTP. |
| `SMTP_USER` / `SMTP_PASSWORD` | vacíos | Credenciales SMTP. |
| `SMTP_FROM` | `no-reply@telemedicina.com` | Remitente. |
| `RESET_CODE_TTL_MINUTES` | `30` | Ventana de validez del código. |
| `RESET_CODE_MAX_ATTEMPTS` | `5` | Intentos fallidos antes del bloqueo. |
| `RESET_CODE_LOCKOUT_MINUTES` | `15` | Duración del bloqueo. |

> En modo dev (`EMAIL_ENABLED=False`) la respuesta de `forgot-password` incluye `debug_code` con el código generado para facilitar la demo. En producción el código solo llega por correo.

### Frontend

| Ruta | Componente | Descripción |
|---|---|---|
| `/recuperar` | `features/auth/recover` | Formulario de correo para solicitar el código. |
| `/recuperar-contrasena` | `features/auth/reset-password` | Correo + código de 6 dígitos + nueva contraseña (con barra de fortaleza y validación de coincidencia). |
| `/login` | `features/auth/login` | Enlace "¿Olvidaste tu contraseña?" → `/recuperar`; banners de "Sesión expirada" (`?expired=true`) y "Contraseña actualizada" (`?reset=true`). |

**Inactividad** (`core/services/inactivity.service.ts`):
- Escucha eventos de actividad (`click`, `keydown`, `mousemove`, `scroll`, `touchstart`, `wheel`) y reinicia un temporizador.
- Timeout configurable en `src/environments/environment.ts` → `inactivityTimeoutMinutes` (default **15 min**).
- Si el usuario marcó **"Mantener sesión iniciada"** (`rememberMe`), el timeout se duplica (30 min).
- Al expirar, limpia tokens y redirige a `/login?expired=true`. Solo se ejecuta en navegador (SSR-safe).

### Prueba del flujo (modo dev, BD local)

1. Backend corriendo (`uvicorn app.main:app --reload --port 8000`) y seed aplicado.
2. `POST /auth/forgot-password` con `{"correo": "admin@telemedicina.com"}` → 200 con `debug_code` (y `[DEV] Código...` en consola).
3. `POST /auth/reset-password` con `{"correo": "...", "codigo": "<debug_code>", "nueva_password": "NuevaPass123"}` → 200.
4. `POST /auth/login` con la nueva contraseña → 200.
5. En el frontend: `/recuperar` → ingresar correo → tomar el código de la consola → `/recuperar-contrasena` → nueva contraseña → login con `?reset=true`.
6. Inactividad: reducir `inactivityTimeoutMinutes` a `0.2` (12 s), iniciar sesión y no tocar nada → redirige a `/login?expired=true`. Restaurar a 15.
7. Pruebas automatizadas: `python scripts/test_endpoints.py` (incluye casos CU23).

---

## Notas y pendientes

- **Secretos hardcodeados:** las claves JWT y credenciales de BD están como valores por defecto en `app/core/config.py`; deben moverse a variables de entorno (`.env`) en producción.
- **Fallback inexistente:** el frontend intenta un endpoint `/usuarios/me` como respaldo en `auth.service.ts`, pero ese endpoint no existe en el backend.
- **CU23 anti fuerza bruta en memoria:** el bloqueo de 5 intentos fallidos vive en memoria del proceso; se reinicia si el servidor se reinicia. El código en sí (HMAC) no necesita estado.

### Completado (CU23)

- ✅ **Hash del doctor corregido:** regenerado con bcrypt válido (antes era placeholder inválido).
- ✅ **Comparación de estado case-insensitive:** `user.estado.lower() != "activo"` en `service.py` (línea 103).
- ✅ **Try-except en SMTP:** `_send_smtp()` captura excepción; si `send_message` ya corrió, no muestra error al usuario; solo log `[SMTP WARNING]`.
- ✅ **4 roles funcionales:** Admin, Médico, Recepción, Paciente con login y recuperación funcionando.
- ✅ **Módulos nuevos creados:** `organization` (Clinica, Rol) y `security` (Notificacion, Auditoria).
- ✅ **Tabla `usuarios` alineada:** campos `id_clinica NOT NULL`, `id_rol NOT NULL`, `estado` default `'ACTIVO'`.

### Pendientes reales

- **Endpoint `/usuarios/me` faltante:** el frontend lo usa como fallback en `auth.service.ts` pero no existe en el backend.
- **Desfase de esquema histórico:** el modelo `usuarios` del backend original no incluía `id_clinica` ni `id_rol` (en el esquema real son obligatorios); ahora alineado con CU23.

---

## Cambios técnicos CU23 — Resumen

| Archivo | Cambio |
|---|---|
| `app/core/email.py` | Try-except en `_send_smtp()` para fallback graceful (no muestra error si `send_message` ya ejecutó) |
| `app/modules/auth/service.py` | Línea 103: `user.estado.lower() != "activo"` — comparación case-insensitive |
| `app/modules/auth/models.py` | Campos `id_clinica` (FK NOT NULL), `id_rol` (FK NOT NULL), `estado` default `'ACTIVO'` |
| `app/modules/organization/models.py` | **NUEVO** — Models `Clinica`, `Rol` con relationships |
| `app/modules/security/models.py` | **NUEVO** — Models `Notificacion`, `Auditoria` |
| `alembic/versions/002_alinear_ddl.py` | Migración idempotente CU23 (crea tablas/columnas si no existen) |
| `alembic/env.py` | Import models nuevos para autogenerate |

---

## Usuarios iniciales (seed)

| Rol | Correo | Contraseña |
|---|---|---|
| Administración | `admin@telemedicina.com` | `admin123` |
| Médico | `doctor@telemedicina.com` | `doctor123` |
| Recepción | `recep@telemedicina.com` | `recep123` |
| Paciente | `paciente@telemedicina.com` | `paciente123` |

---

## Enlaces útiles