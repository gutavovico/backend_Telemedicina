# README_Miguel — Plataforma de Telemedicina

Proyecto de la asignatura **Sistemas de Información 2** para el **Hospital San Juan de Dios**.
Sistema de gestión médica con telemedicina: agendamiento de citas, teleconsultas, historia clínica digital, recetas electrónicas, laboratorio y asistencia por IA.

El proyecto está dividido en **tres repositorios independientes**:

| Carpeta | Rol | Tecnología |
|---|---|---|
| `backend_Telemedicina/` | API REST + lógica de negocio + base de datos | FastAPI, SQLAlchemy, Alembic, PostgreSQL |
| `frontend_Telemedicina/` | Interfaz de usuario (Web Admin) | Angular 21, Angular Material, Tailwind CSS |
| `mobile_telemedicina/` | Interfaz móvil (PWA) | Flutter Web 3.47, Provider, Material 3 |

## Estado actual del avance

- **CU01 Iniciar sesión (completado):** registro de usuarios, login, refresh de tokens y perfil autenticado funcionando de punta a punta (backend + frontend).
- **CU23 Recuperar Acceso (completado):** recuperación de contraseña por correo con código de 6 dígitos (backend + frontend) y cierre de sesión automático por inactividad (frontend). Paquete (pkg) **Autenticación y seguridad**.
  - Hash del doctor corregido (bcrypt válido)
  - Comparación de estado case-insensitive (`user.estado.lower()`)
  - Try-except en SMTP para fallback graceful (no muestra error si el correo se envió)
  - 4 roles funcionando: Administrador, Médico, Recepción, Paciente
  - Módulos nuevos: `organization` (Clinica, Rol) y `security` (Notificacion, Auditoria)
- **CU23 Recuperar Acceso en móvil (completado):** Flutter Web (PWA) con pantallas Forgot/Reset Password, integración con endpoints backend existentes.
- **Módulos pendientes:** citas, historias clínicas, comunicaciones, asistencia IA y analítica existen como esqueletos vacíos (`app/modules/` en backend y `features/` en frontend), sin lógica implementada.

| Estado | Descripción |
|---|---|
| Estructura base FE/BE | Completado |
| Autenticación (registro, login, refresh) | Completado |
| CU23 Recuperar Acceso (correo + inactividad) | Completado |
| CU23 Recuperar Acceso móvil (Flutter Web) | Completado |
| Citas (`appointments`) | Pendiente |
| Historias clínicas (`medical-records`) | Pendiente |
| Comunicaciones (`communications`) | Pendiente |
| Asistente IA (`ai_assistant`) | Pendiente |
| Analítica / reportes (`analytics`) | Pendiente |

---

## Stack tecnológico

| Capa | Tecnología | Detalle |
|---|---|---|
| Frontend (Admin) | Angular 21.2 (CLI `ng`) | Standalone components + signals, SSR habilitado |
| UI | Angular Material 21 + Tailwind CSS 4 | Componentes y estilos |
| Móvil (PWA) | Flutter Web 3.47 | Compila a JS/HTML/CSS, Provider state management, Material 3 theming |
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
│   │   │   └── analytics/       # vacío
│   │   └── main.py              # FastAPI app + CORS + routers
│   ├── alembic/                 # Migraciones
│   ├── scripts/
│   │   ├── seed.py              # Usuarios iniciales
│   │   └── test_endpoints.py    # Pruebas de endpoints (incluye CU23)
│   └── requirements.txt
├── frontend_Telemedicina/
│   ├── src/
│   │   ├── app/
│   │   │   ├── core/
│   │   │   │   ├── services/auth.service.ts   # Login, tokens, perfil, recuperación
│   │   │   │   ├── services/inactivity.service.ts # Cierre por inactividad (CU23)
│   │   │   │   ├── guards/auth.guard.ts       # Protección de rutas
│   │   │   │   ├── interceptors/auth.interceptor.ts # JWT + auto-refresh
│   │   │   │   └── models/auth.models.ts
│   │   │   ├── features/
│   │   │   │   ├── home/          # Landing page
│   │   │   │   ├── auth/login/    # Inicio de sesión
│   │   │   │   ├── auth/register/ # Registro
│   │   │   │   ├── auth/recover/  # Recuperar contraseña (solicitar código)
│   │   │   │   ├── auth/reset-password/ # Restablecer contraseña (código)
│   │   │   │   ├── appointments/  # vacío
│   │   │   │   ├── medical-records/ # vacío
│   │   │   │   ├── communications/ # vacío
│   │   │   │   ├── ai-assistant/  # vacío
│   │   │   │   └── analytics/     # vacío
│   │   │   └── shared/
│   │   │       ├── components/header/  # Header con menú de usuario
│   │   │       └── components/footer/  # Footer
│   │   ├── environments/          # environment.ts (apiUrl localhost:8000)
│   │   └── styles.css
│   └── package.json
└── mobile_telemedicina/
    ├── lib/
    │   ├── core/
    │   │   ├── config/api_config.dart      # URLs backend (10.0.2.2 para emulador)
    │   │   ├── network/api_client.dart     # HTTP client con auth interceptors
    │   │   ├── storage/secure_storage_service.dart # Tokens + user cache
    │   │   └── theme/                      # Colors, typography, theme
    │   ├── features/
    │   │   └── auth/
    │   │       ├── data/
    │   │       │   ├── models/auth_models.dart       # ← +Forgot/Reset models
    │   │       │   └── datasources/auth_remote_datasource.dart # ← +forgot/reset
    │   │       ├── presentation/
    │   │       │   ├── controllers/auth_controller.dart      # ← +forgot/reset methods
    │   │       │   ├── screens/
    │   │       │   │   ├── login_screen.dart                 # ← +link "¿Olvidaste?"
    │   │       │   │   ├── forgot_password_screen.dart       # 🆕 Nueva
    │   │       │   │   ├── reset_password_screen.dart        # 🆕 Nueva
    │   │       │   │   ├── register_screen.dart
    │   │       │   │   ├── splash_screen.dart
    │   │       │   │   └── home_screen.dart
    │   │       │   └── widgets/              # CustomTextField, AuthButton, AuthBanner, etc.
    │   └── main.dart                       # ← +rutas /forgot-password, /reset-password
    ├── pubspec.yaml
    └── README.md
```

---

## Cómo levantar el proyecto

### Requisitos previos

- Python 3.10+ (backend)
- Node.js (Angular CLI 21)
- Flutter 3.47+ (mobile_telemedicina)
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

### Móvil (Flutter Web / PWA)

```bash
cd mobile_telemedicina
flutter pub get
flutter run -d chrome          # Dev con hot reload
# Para probar en "móvil": F12 → Ctrl+Shift+M → Pixel 7 / iPhone
flutter build web              # Build producción (output: build/web/)
```

**Nota:** Flutter Web **no corre en emulador Android**. Se prueba en Chrome/Edge con **Device Toolbar** (F12 → Ctrl+Shift+M) simulando Pixel 7, iPhone, etc. El backend URL en `api_config.dart` usa `10.0.2.2:8000` para Android/emulador y `192.168.100.30:8000` para device físico/web.

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

- La tabla `usuarios` se relaciona con `clinicas` y `roles` (1:1) y es la base del módulo de autenticación actual.
- Roles iniciales insertados por el script: Administración, Médico, Recepción, Paciente.

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

### Frontend (Angular)

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

### Móvil (Flutter Web)

| Ruta | Pantalla | Descripción |
|---|---|---|
| `/forgot-password` | `ForgotPasswordScreen` | Formulario email → "Enviar Código" → navega a ResetPasswordScreen |
| `/reset-password` | `ResetPasswordScreen` | 6 dígitos (6 TextField con auto-focus) + nueva contraseña + confirmar → "Restablecer" |
| `/login` | `LoginScreen` | Link "¿Olvidaste tu contraseña?" → `/forgot-password` |

**Validaciones frontend:**
- Email: `Validators.validateEmail`
- Código: 6 dígitos numéricos (auto-focus entre campos)
- Nueva contraseña: `Validators.validatePassword` (mín 6 caracteres)
- Confirmar: Debe coincidir con nueva

**Seguridad:** Reusa lógica HMAC/anti-fuerza-bruta del backend (mismos endpoints).

### Prueba del flujo (modo dev, BD local)

1. Backend corriendo (`uvicorn app.main:app --reload --port 8000`) y seed aplicado.
2. `POST /auth/forgot-password` con `{"correo": "admin@telemedicina.com"}` → 200 con `debug_code` (y `[DEV] Código...` en consola).
3. `POST /auth/reset-password` con `{"correo": "...", "codigo": "<debug_code>", "nueva_password": "NuevaPass123"}` → 200.
4. `POST /auth/login` con la nueva contraseña → 200.
5. En el frontend (Angular): `/recuperar` → ingresar correo → tomar el código de la consola → `/recuperar-contrasena` → nueva contraseña → login con `?reset=true`.
6. En el móvil (Flutter Web): `/forgot-password` → email → "Enviar Código" → `/reset-password` → 6 dígitos + nueva pass → login.
7. Inactividad: reducir `inactivityTimeoutMinutes` a `0.2` (12 s), iniciar sesión y no tocar nada → redirige a `/login?expired=true`. Restaurar a 15.
8. Pruebas automatizadas: `python scripts/test_endpoints.py` (incluye casos CU23).

---

## Notas y pendientes

- **Secretos hardcodeados:** las claves JWT y credenciales de BD están como valores por defecto en `app/core/config.py`; deben moverse a variables de entorno (`.env`) en producción.
- **Desfase de esquema:** el modelo `usuarios` del backend actual no incluye `id_clinica` ni `id_rol` (en el esquema real son obligatorios). Habrá que alinearlo al desarrollar los módulos de organización.
- **Fallback inexistente:** el frontend intenta un endpoint `/usuarios/me` como respaldo en `auth.service.ts`, pero ese endpoint no existe en el backend.
- **Estados en mayúsculas:** la BD real usa `'ACTIVO'`/`'PROGRAMADA'`, mientras el backend compara con `'activo'` en minúsculas. Alinear al implementar los estados.
- **CU23 anti fuerza bruta en memoria:** el bloqueo de 5 intentos fallidos vive en memoria del proceso; se reinicia si el servidor se reinicia. El código en sí (HMAC) no necesita estado.
- **Flutter Web vs Emulador:** `mobile_telemedicina` es PWA (Flutter Web), no app nativa. Se prueba en Chrome + Device Toolbar, no en emulador Android.

---

## Enlaces útiles

- Backend docs (Swagger): http://localhost:8000/docs
- Angular CLI: https://github.com/angular/angular-cli
- Flutter Web: https://flutter.dev/web
- Neon (PostgreSQL): https://neon.tech