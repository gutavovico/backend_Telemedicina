---

## Guía de Prueba: CU23, CU10, CU12 — Web PC y Móvil Web

### Credenciales de Prueba (Neon + Seed)

Todas las cuentas usan `password123` salvo los admins/doctores con sus propios passwords.

| Rol | Email | Password | Tenant (Clínica) | Permisos Clave |
|-----|-------|----------|------------------|----------------|
| **ADMIN** | `admin@telemedicina.com` | `admin123` | Clinica Central (1) | Todos |
| **MÉDICO** | `doctor@telemedicina.com` | `doctor123` | Clinica Central (1) | Todos (incl. resultados lab) |
| **RECEPCIÓN** | `recepcion@telemedicina.com` | `recepcion123` | Clinica Central (1) | Sin resultados lab |
| **PACIENTE (Carlos)** | `paciente.carlos@telemedicina.com` | `paciente123` | Clinica Central (1) | Solo sus docs |
| **PACIENTE (Ana)** | `paciente.ana@telemedicina.com` | `paciente123` | Clinica Central (1) | Solo sus docs |
| **MÉDICO (Norte)** | `medico.norte@telemedicina.com` | `medico123` | Clinica Norte (2) | Solo tenant 2 |
| **PACIENTE (Luis Norte)** | `paciente.luis@telemedicina.com` | `paciente123` | Clinica Norte (2) | Solo tenant 2 |

> **Nota:** Para CU10 (Órdenes de Laboratorio), los exámenes del catálogo son: `HEMOGRAMA`, `GLUCOSA`, `CREATININA`, `UREA`, `COLESTEROL_TOTAL`, `TRIGLICERIDOS`, `HEMOGLOBINA_GLICADA`, `TGO_TGP`, `ORINA_COMPLETA`, `COPROLOGICO`.

---

## 🚀 Levantar los 3 Servicios (3 CMD separadas)

### Terminal 1 — Backend (FastAPI)
```cmd
cd /d D:\Proyectos si 2\PROYECTO SI2\backend_Telemedicina
..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```
> URL: http://127.0.0.1:8000 | Docs: http://127.0.0.1:8000/docs

---

### Terminal 2 — Frontend Web (Angular)
```cmd
cd /d D:\Proyectos si 2\PROYECTO SI2\frontend_Telemedicina
npm run start
```
> URL: http://localhost:4200

---

### Terminal 3 — Mobile Web (Flutter)
```cmd
cd /d D:\Proyectos si 2\PROYECTO SI2\mobile_telemedicina
flutter run -d chrome --web-port 8080
```
> URL: http://localhost:8080

---

## 🔐 Credenciales Neon (Base de Datos PostgreSQL)

Estas son las credenciales configuradas en `.env` del backend para conectar a Neon:

```env
DB_NAME=Telemedicina
DB_USER=neondb_owner
DB_PASSWORD=npg_yMFcXO8AYpI1
DB_HOST=ep-steep-shadow-ay9kgisu-pooler.c-5.us-east-2.aws.neon.tech
DB_PORT=5432
```

**Connection String completa:**
```
postgresql://neondb_owner:npg_yMFcXO8AYpI1@ep-steep-shadow-ay9kgisu-pooler.c-5.us-east-2.aws.neon.tech:5432/Telemedicina?sslmode=require
```

> **Nota:** La base de datos ya tiene las migraciones aplicadas (hasta `007_crear_catalogo_examenes`) y el seed de datos cargado (cuentas de prueba, catálogo de exámenes, permisos).

---

## 🚀 Levantar los 3 Servicios (3 CMD separadas)

### Terminal 1 — Backend (FastAPI)
```cmd
cd /d D:\Proyectos si 2\PROYECTO SI2\backend_Telemedicina
..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### Terminal 2 — Frontend Web (Angular)
```cmd
cd /d D:\Proyectos si 2\PROYECTO SI2\frontend_Telemedicina
npm run start
```

### Terminal 3 — Mobile Web (Flutter)
```cmd
cd /d D:\Proyectos si 2\PROYECTO SI2\mobile_telemedicina
flutter run -d chrome --web-port 8080
```

---

## 🔐 Credenciales de Prueba (Neon + Seed)

Todas las cuentas usan `password123` salvo los admins/doctores con sus propios passwords.

| Rol | Email | Password | Tenant (Clínica) | Permisos Clave |
|-----|-------|----------|------------------|----------------|
| **ADMIN** | `admin@telemedicina.com` | `admin123` | Clinica Central (1) | Todos |
| **MÉDICO** | `doctor@telemedicina.com` | `medico123` | Clinica Central (1) | Todos (incl. resultados lab) |
| **RECEPCIÓN** | `recepcion@telemedicina.com` | `recepcion123` | Clinica Central (1) | Sin resultados lab |
| **PACIENTE (Carlos)** | `paciente.carlos@telemedicina.com` | `paciente123` | Clinica Central (1) | Solo sus docs |
| **PACIENTE (Ana)** | `paciente.ana@telemedicina.com` | `paciente123` | Clinica Central (1) | Solo sus docs |
| **MÉDICO (Norte)** | `medico.norte@telemedicina.com` | `medico123` | Clinica Norte (2) | Solo tenant 2 |
| **PACIENTE (Luis Norte)** | `paciente.luis@telemedicina.com` | `paciente123` | Clinica Norte (2) | Solo tenant 2 |

> **Nota:** Para CU10 (Órdenes de Laboratorio), los exámenes del catálogo son: `HEMOGRAMA`, `GLUCOSA`, `CREATININA`, `UREA`, `COLESTEROL_TOTAL`, `TRIGLICERIDOS`, `HEMOGLOBINA_GLICADA`, `TGO_TGP`, `ORINA_COMPLETA`, `COPROLOGICO`.

---

## CU23 — Recuperar Acceso + Cierre por Inactividad

**Descripción:** Recuperación de contraseña por **correo electrónico** (código 6 dígitos, 30 min, 5 intentos máx) + cierre automático de sesión por inactividad (15 min, aviso 60s). **El canal SMS está deshabilitado; solo email.**

---

### Web PC (Angular — http://localhost:4200)

#### 1. Recuperar contraseña por EMAIL (Gmail real configurado)
1. Ir a `/recuperar` (o click "¿Olvidaste tu contraseña?" en Login)
2. Ingresar email: `doctor@telemedicina.com` (o cualquier email registrado)
3. Click **"Enviar código de recuperación"** (canal email por defecto)
4. **Respuesta exitosa:** Toast verde "Solicitud enviada. Si el correo está registrado, recibirás un código..."
5. **En producción (EMAIL_ENABLED=True):** El código de 6 dígitos llega al email real (Gmail configurado con App Password)
   - Revisar bandeja de entrada/spam en `admin.telemedicina@gmail.com` (desde: `Telemedicina - Hospital San Juan de Dios <admin.telemedicina@gmail.com>`)
   - Asunto: "Recuperación de contraseña - Hospital San Juan de Dios"
7. Ir a `/recuperar-contrasena`
8. Ingresar email + código recibido + nueva contraseña (`NuevaPass123`)
9. Click **"Restablecer"** → "Contraseña restablecida exitosamente" → Redirige a Login

#### 2. Casos Edge
- **Email no registrado:** `noexiste@test.com` → Mismo mensaje genérico (anti-enumeración)
- **Canal inválido:** `telegram` → 422 Validation Error (solo `email` permitido)

#### 3. Cierre por Inactividad (Auto)
- Ventana: **15 minutos** sin actividad
- Aviso: **60 segundos** antes con cuenta regresiva
- Botón **"Seguir conectado"** renueva sesión (POST `/auth/session/continue`)
- Al agotar: Limpia localStorage + redirige a `/login?inactive=true`
- **Reconciliación:** Al recuperar foco/visibilidad, sincroniza reloj con `GET /auth/session`

---

### Móvil Web (Flutter Web — http://localhost:8080)

#### CU23 — Recuperar Acceso + Inactividad

**Pantallas:**
- `ForgotPasswordScreen`: **Solo canal Email** (SMS deshabilitado — SegmentedButton removido) → Email → Enviar código
- `ResetPasswordScreen`: Código + nueva contraseña → Redirige a Login
- `InactivityWarningListener`: Overlay con cuenta regresiva 60s + botón "Seguir conectado"

**Flujos:**
1. **Recuperar por Email:** Login screen → "¿Olvidaste tu contraseña?" → Email → "Enviar código" → Revisa Gmail real → `/recuperar-contrasena` → Código + nueva pass
2. **Inactividad:** Auto-detecta background/foreground → Aviso 60s antes → "Seguir conectado" renueva sesión → Expira → Limpia storage → Redirige a Login con `?inactive=true`

> **Configuración Email (Gmail) en `.env`:**
> ```env
> EMAIL_ENABLED=True
> SMTP_HOST=smtp.gmail.com
> SMTP_PORT=587
> SMTP_USER=admin.telemedicina@gmail.com
> SMTP_PASSWORD=tzwmnnlzksgsonjq  # App Password (sin espacios)
> SMTP_FROM=admin.telemedicina@gmail.com
> EMAIL_FROM_NAME=Telemedicina - Hospital San Juan de Dios
> EMAIL_ENABLED=True
> SMS_PROVIDER=console  # SMS deshabilitado
> ```

---

## CU10 — Emitir Órdenes de Laboratorio

**Descripción:** Crear orden en borrador → Seleccionar exámenes del catálogo → Firmar digitalmente (HMAC-SHA256) → Generar PDF → Indexar en HCE (`documentos_clinicos` tipo `ORDEN_LAB`) → Descarga segura.

---

### Web PC (Angular — http://localhost:4200)

#### Roles que pueden **CREAR + FIRMAR**: **MÉDICO** (propias), **ADMIN** (todas)
#### Roles que pueden **VER/DESCARGAR**: **ADMIN**, **RECEPCIÓN**, **PACIENTE** (propias vía HCE)

#### 1. Crear Orden (Borrador) — Solo MÉDICO
1. Login: `doctor@telemedicina.com` / `doctor123`
2. Ir a **Órdenes de Laboratorio** (menú lateral o `/ordenes-laboratorio`)
3. Click **"Nueva Orden"** (`/ordenes-laboratorio/nueva`)
4. **Paciente:** Buscar/seleccionar ID (ej: `10` = Carlos Mamani)
5. **Exámenes:** 
   - Click **"Añadir examen"**
   - Escribir código: `HEMOGRAMA` → autocompletado muestra "Hemograma Completo (HEMATOLOGIA)"
   - Indicaciones: `En ayunas 12 horas`
   - Click **"Añadir examen"** → `GLUCOSA` → `Post-prandial 2h`
5. Click **"Crear orden en borrador"**
6. **Resultado:** Redirige a detalle → Badge **"BORRADOR"**, exams listados, botón **"Firmar y emitir orden"**

#### 2. Firmar y Emitir — Solo MÉDICO creador
1. En detalle de orden BORRADOR → Click **"Firmar y emitir orden"**
2. **Backend:** Firma HMAC-SHA256 (clave derivada HKDF por médico) + Genera PDF (reportlab) + Sube a storage + Indexa en `documentos_clinicos` tipo `ORDEN_LAB`
4. **Resultado:** Badge **"FIRMADA"**, muestra **Firma Digital** (64 chars hex) + **Hash SHA-256** del PDF
5. **HCE:** La orden aparece en `documentos_clinicos` tipo `ORDEN_LAB` → visible en módulo Documentos

#### 3. Listar y Filtrar
- **MÉDICO:** Solo sus órdenes (`/ordenes-laboratorio` + filtro `id_medico = current_user`)
- **ADMIN/RECEPCIÓN:** Todas del tenant
- Filtros: Estado (BORRADOR/FIRMADA/ANULADA), Paciente, Fecha desde/hasta, Búsqueda por examen/paciente

#### 4. Descargar PDF
- En detalle de orden **FIRMADA** → Click **"Generar URL de descarga"** → **"Descargar PDF"**
- URL firmada ≤ 900s (MinIO presigned o endpoint local autenticado)
- Registra auditoría `DESCARGAR_ORDEN_LABORATORIO` + notifica al paciente

#### 5. PACIENTE ve sus órdenes
- Login: `paciente.carlos@telemedicina.com` / `paciente123`
- En **Documentos Clínicos** (`/mis-documentos`) → Filtro tipo `ORDEN_LAB` → ve sus órdenes firmadas + descarga

---

### Móvil Web (Flutter Web — http://localhost:8080)

#### CU10 — Órdenes de Laboratorio

**Pantallas:**
- `OrdenesLaboratorioListScreen`: ListView + filtros chips (Estado) + pull-to-refresh + FAB "Nueva Orden"
- `OrdenLaboratorioFormScreen`: Selector exámenes (chips + bottom sheet búsqueda) + indicaciones por examen + botón "Firmar y emitir"
- `OrdenLaboratorioDetailScreen`: Detalle + firma digital/hash + botón descarga → `DocumentViewerScreen` (syncfusion_flutter_pdfviewer)

**Flujo completo MÉDICO:**
1. Login: `doctor@telemedicina.com` / `doctor123`
2. Tap **Órdenes de Laboratorio** (tab inferior o drawer lateral)
3. Tap **FAB +** → Nueva Orden
3. Buscar paciente (ID `10` = Carlos Mamani)
4. **Añadir examen**: Tap "Añadir examen" → Buscar `HEMOGRAMA` → Indicaciones: `En ayunas 12 horas`
5. Tap **"Añadir examen"** → Buscar `GLUCOSA` → Indicaciones: `Post-prandial 2h`
6. Tap **"Crear orden en borrador"** → Redirige a detalle → Badge **BORRADOR**
6. Tap **"Firmar y emitir orden"** → Badge **FIRMADA**, muestra Firma Digital + Hash SHA-256
7. Tap **"Descargar PDF"** → `DocumentViewerScreen` con zoom/navegación páginas

**Flujo PACIENTE:**
1. Login: `paciente.carlos@telemedicina.com` / `paciente123`
2. Tap **Mis Documentos** → Filtro `ORDEN_LAB` → Ve sus órdenes + descarga

---

## CU12 — Consultar Documentos Clínicos y Exámenes

**Descripción:** Buscar, listar, ver detalle y descargar recetas, órdenes médicas, resultados de laboratorio, certificados e indicaciones.

---

### Web PC (Angular — http://localhost:4200)

#### Roles y Permisos
| Rol | Permisos |
|-----|----------|
| **ADMIN** | Todos los tipos, crear/actualizar/anular, descargar, auditoría |
| **MÉDICO** | Igual ADMIN + crear/actualizar sus docs |
| **RECEPCIÓN** | RECETA, ORDEN_LAB, CERTIFICADO, INDICACIÓN (NO `RESULTADO_LAB`) |
| **PACIENTE** | Solo sus propios documentos |

#### 1. Listado General — ADMIN/MÉDICO/RECEPCIÓN
1. Login según rol
2. Ir a **Documentos Clínicos** (`/documentos`)
3. Filtros disponibles:
   - **Tipo:** `RECETA`, `ORDEN_LAB`, `RESULTADO_LAB`, `CERTIFICADO`, `INDICACION`
   - **Paciente:** ID (solo ADMIN/MEDICO/RECEPCIÓN)
   - **Fechas:** Desde / Hasta
   - **Búsqueda:** Por título
   - **Paginación:** 10/25/50 por página

#### 2. Mis Documentos — PACIENTE
1. Login: `paciente.carlos@telemedicina.com` / `paciente123`
2. Ir a **Mis Documentos** (`/mis-documentos`)
3. Solo ve sus documentos (filtro automático `id_paciente`)

#### 3. Documentos de Paciente — ADMIN/MEDICO/RECEPCIÓN
1. Ir a `/documentos/paciente/{idPaciente}` (ej: `/documentos/paciente/10`)
2. Lista documentos de ese paciente en el tenant

#### 4. Detalle + Descarga
1. Click fila → Detalle (`/documentos/{id}` o `/mis-documentos/{id}`)
2. Ver metadata: tipo, título, fecha, paciente, firmante, descripción, metadatos
3. **Descargar:** Click **"Descargar"** → genera URL firmada ≤ 900s
4. **Auditoría + Notificación:** Automática al descargar (registra en `auditoria`, notifica al paciente)

#### 5. RECEPCIÓN — Restricción RESULTADO_LAB
- En lista: Select `RESULTADO_LAB` → Toast 403 "Permiso denegado..."
- Click Ver/Descargar en resultado lab → 403
- Otros tipos (RECETA, ORDEN_LAB, CERTIFICADO) → OK

---

### Móvil Web (Flutter Web — http://localhost:8080)

#### CU12 — Documentos Clínicos y Exámenes

**Pantallas:**
- `DocumentsListScreen`: ListView + chips filtros (Todos/Recetas/Órdenes Lab/Resultados Lab/Certificados) + pull-to-refresh
- `DocumentViewerScreen`: `syncfusion_flutter_pdfviewer` con zoom, navegación páginas
- Descarga: `ClinicalDocumentService.downloadDocumentBytes()` → guarda en dispositivo

**Flujos por rol:**
| Rol | Qué hacer en móvil |
|-----|-------------------|
| **MÉDICO** | Tap **Documentos** → Filtros chips → Tap fila → Ver detalle → Descargar |
| **RECEPCIÓN** | Igual pero `RESULTADO_LAB` → 403 al tap |
| **PACIENTE** | Tap **Mis Documentos** → Solo sus docs → Tap → Ver/Descargar |

**Navegación:**
- **Drawer lateral** (hamburguesa ☰): Menú con Documentos, Órdenes Lab, Perfil, Cerrar sesión
- **Tabs inferiores**: Home | Documentos | Órdenes Lab | Perfil

---

## CU23 — Recuperar Acceso + Inactividad (Móvil Web)

**Pantallas:**
- `ForgotPasswordScreen`: **Solo canal Email** (SMS deshabilitado) → Email → Enviar código
- `ResetPasswordScreen`: Código + nueva contraseña → Redirige a Login
- `InactivityWarningListener`: Overlay con cuenta regresiva 60s + botón "Seguir conectado"

**Flujos:**
1. **Recuperar por Email:** Login screen → "¿Olvidaste tu contraseña?" → Email → "Enviar código" → Revisa Gmail real → `/recuperar-contrasena` → Código + nueva pass
2. **Inactividad:** Auto-detecta background/foreground → Aviso 60s antes → "Seguir conectado" renueva sesión → Expira → Limpia storage → Redirige a Login con `?inactive=true`

---

## Resumen: Qué probar en cada plataforma

| CU | Web PC ✅ | Móvil Web ✅ |
|----|-----------|--------------|
| **CU23 - Recuperar** | Email real → Gmail → Código → Reset | Igual (solo email) |
| **CU23 - Inactividad** | Aviso 60s + overlay + reconcilia foco | Overlay nativo + reconcilia background/foreground |
| **CU10 - Crear** | Form + Autocomplete + Chips | Form + Bottom Sheet + Chips |
| **CU10 - Firmar** | Click → PDF nueva pestaña | Tap → Visor nativo (zoom pinch) |
| **CU10 - HCE** | Ver en `/documentos` | Ver en "Mis Documentos" + filtro `ORDEN_LAB` |
| **CU12 - Listar** | Sidebar + Filtros dropdown | Chips + Pull-to-refresh |
| **CU12 - Visor PDF** | Nueva pestaña + zoom botones | Visor nativo + pinch-to-zoom |
| **CU12 - Descarga** | Blob + saveAs | Archivo local (descarga nativa) |
| **CU12 - Permisos** | RECEPCIÓN sin resultados | RECEPCIÓN sin resultados (403 tap) |

---

## Verificación Rápida (Health Check)

```bash
# Backend API
curl http://localhost:8000/health
# {"status":"ok","app":"Telemedicina API","version":"1.0.0"}

# Frontend
curl http://localhost:4200
# HTML con <app-root>

# Mobile Web
curl http://localhost:8080
# HTML con Flutter bootstrap

# OpenSpec validation (en cada repo specs/Telemmedicina-SDD)
$env:OPENSPEC_TELEMETRY=0; npx @fission-ai/openspec@latest doctor
$env:OPENSPEC_TELEMETRY=0; npx @fission-ai/openspec@latest validate --all --strict
```

---

## Tests Completos

```bash
# Backend (93 tests)
cd backend_Telemedicina
.\venv\Scripts\python.exe -m pytest tests/ -v

# Frontend (37 tests, 92.78% cov)
cd frontend_Telemedicina
npm run test:vitest
npm run test:e2e          # Cypress E2E

# Mobile (50 tests)
cd mobile_telemedicina
flutter test --coverage
flutter analyze

# OpenSpec (3 repos)
$env:OPENSPEC_TELEMETRY=0; npx @fission-ai/openspec@latest validate --all --strict
```

---

## Solución de Problemas Comunes

| Problema | Causa | Solución |
|----------|-------|----------|
| `404` al crear orden | Paciente no existe en tenant | Verificar `id_paciente` en `pacientes` |
| `403` al firmar orden ajena | MÉDICO intenta firmar orden de otro | Solo creador puede firmar |
| `403` RECEPCIÓN en RESULTADO_LAB | Permiso faltante | Por diseño, RECEPCIÓN no tiene `documents:read:lab_results` |
| PDF no carga en visor | Worker PDF.js faltante | Verificar `pdf.worker.min.mjs` en assets |
| Cross-tenant 404 | Tenant incorrecto | Header `X-Tenant-ID` o claim `id_clinica` en JWT |
| Email no llega a Gmail | Spam / App Password incorrecto | Revisar spam, verificar App Password (16 chars sin espacios), `EMAIL_ENABLED=True` |

---

## Próximos Módulos Pendientes

- [ ] **CU09** — Gestionar Fichas (Pacientes)
- [ ] **CU11** — Emitir Recetas
- [ ] **CU21** — Auditoría Administrativa
- [ ] **Appointments** — Citas Médicas
- [ ] **AI Assistant** — Asistente IA

---

> **Última actualización:** 2026-10-04 — CU10 implementado y verificado en Neon. 180 tests pasando (93 backend + 37 frontend + 50 mobile).