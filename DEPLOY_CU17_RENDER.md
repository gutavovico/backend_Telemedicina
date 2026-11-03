# Despliegue de CU17 en Render (Android)

Esta guía corresponde al código actual del repositorio `backend` y a la app
`mobile_telemedicina`. La API pública existente se llama
`backend-telemedicina.onrender.com`. Los cambios locales deben estar en la rama
que Render despliega antes de configurar los servicios; Render no lee el árbol
de trabajo de esta computadora.

**Entrega para el líder:** `render.yaml` define la API y el Cron Job en un solo
Blueprint. Revisar en Render el nombre, plan, región y rama del servicio web
existente antes de sincronizarlo para evitar crear otro servicio o alterar su
configuración. El archivo SQL separado
`deploy/cu17_neon_desde_backup01ab23cd.sql` fue generado por las migraciones
CU17 y su revisión de unión con copias de seguridad. Usarlo solo si Neon está
exactamente en `backup01ab23cd` y no existe ninguna tabla CU17. Si la base está
en `014_operaciones_dosis_cu17`, ejecutar `python -m alembic upgrade head` para
aplicar la rama de copias de seguridad y la unión, sin ejecutar ese SQL. Si está
en `f7a8b9c0d1e2`, usar también `alembic upgrade head` para aplicar ambas ramas.
La revisión final esperada es `cu17_backup_merge_015`. El SQL rechaza una base
con revisión o tablas inesperadas.

## 1. Preparar la base y la API

1. Identificar la base PostgreSQL que usa el servicio Render. Este backend lee
   `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD`; no lee una variable
   `DATABASE_URL` del entorno. Para Neon configurar también `DB_SSLMODE=require`
   y `DB_CHANNEL_BINDING=require` en API y Cron Job. Conservar los secretos JWT y los demás
   valores que ya utiliza el servicio.
2. Guardar una copia verificable de esa base antes de migrarla. Comprobar la
   revisión actual de `alembic_version` y aplicar `python -m alembic upgrade head`
   exactamente una vez sobre la base objetivo. En un servicio web de pago, este
   comando puede ser el **Pre-Deploy Command** de Render. En el plan gratuito no
   está disponible; ejecutarlo desde una estación administrativa con acceso a la
   misma base y las variables `DB_*` correctas, antes de activar el código nuevo.
3. En el servicio web existente, usar el directorio raíz del repositorio
   `backend`, **Build Command** `pip install -r requirements.txt` y **Start Command**
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. El archivo
   `.python-version` fija Python 3.12 para instalaciones nuevas. Si Render ya
   define `PYTHON_VERSION`, ese valor tiene prioridad: usar Python 3.12.x.
4. Tras el despliegue, confirmar que `/openapi.json` contiene
   `/api/v1/tratamientos`, `/api/v1/tratamientos/avisos` y
   `/api/v1/tratamientos/dispositivos`.

## 2. Configurar FCM sin publicar secretos

La rama principal también incorpora copias de seguridad. Su ejecución requiere
`pg_dump` en el servicio web y un destino adecuado para los archivos de
`BACKUP_DIR`; verificar ambos antes de activar la programación de backups en
Render. Es una decisión de despliegue independiente del worker CU17.

En **Environment > Secret Files** del servicio web, subir el contenido del JSON
de la cuenta de servicio Firebase con el nombre
`cu17-firebase-service-account.json`. Render lo expone en
`/etc/secrets/cu17-firebase-service-account.json`. No subir ese JSON ni `.env`
al repositorio, a un APK o a un comentario de despliegue.
Compartir con el líder solo el JSON de la **cuenta de servicio** por un canal
privado adecuado para secretos; no compartir la contraseña de la cuenta
personal de Google/Firebase. El archivo JSON contiene una clave privada y su
acceso debe limitarse a quienes administran el despliegue.

Configurar estas variables en Render:

| Variable | Valor |
| --- | --- |
| `CU17_FCM_PROJECT_ID` | `telemedicina-si2` |
| `CU17_FCM_SERVICE_ACCOUNT_FILE` | `/etc/secrets/cu17-firebase-service-account.json` |
| `CU17_DEVICE_TOKEN_KEY` | Clave Fernet estable. Si Render usa la misma base que la prueba local, copiar exactamente la clave del `.env` local. |
| `CU17_SYSTEM_USER_IDS_JSON` | Mapa de clínica a usuario `SISTEMA` activo. Para la base de pruebas actual: `{"1":57}`; verificar el ID en la base objetivo. |

El proyecto del archivo de servicio debe coincidir con
`CU17_FCM_PROJECT_ID`. El archivo Android `google-services.json` pertenece a la
app, no al backend. La clave Fernet es necesaria para descifrar los
identificadores de dispositivos guardados; rotarla exige una migración o volver
a registrar los dispositivos.

## 3. Programar el worker de recordatorios

Crear un **Cron Job** de Render desde el mismo repositorio y rama que la API:

| Campo | Valor |
| --- | --- |
| Root Directory | Raíz del repositorio `backend` |
| Build Command | `pip install -r requirements.txt` |
| Schedule | `*/5 * * * *` (cada cinco minutos, UTC) |
| Command | `python -m scripts.run_cu17_notificaciones --once` |

El Cron Job necesita los mismos `DB_*`, `CU17_*` y archivo secreto que la API.
Un **Environment Group** de Render puede compartirlos entre los dos servicios.
El worker se ejecuta una vez y sale; sus logs deben mostrar los avisos y
entregas del ciclo. Render garantiza una sola ejecución simultánea del mismo
Cron Job. El envío saliente a FCM HTTP v1 requiere que la cuenta de servicio
tenga permisos para el proyecto Firebase.

Antes de activar el Cron Job sobre la base de prueba actual, decidir si se
conservará el plan de demostración CU17 **#68**. Está activo y el worker puede
generar recordatorios para ese paciente. Después de la verificación manual,
el médico tratante puede finalizarlo mediante la API CU17 con motivo de prueba.

## 4. Comprobaciones previas y prueba sin USB

En un entorno con las variables y el archivo secreto configurados, ejecutar:

```bash
python -m scripts.check_cu17_deploy
python -m scripts.run_cu17_notificaciones --once
```

La primera orden es de solo lectura: valida configuración FCM, coincidencia del
proyecto Firebase, revisión Alembic, tablas, usuarios `SISTEMA` y que la clave
Fernet descifra al menos un dispositivo activo si existe. No envía push ni
imprime secretos. La segunda genera y despacha recordatorios pendientes.

La variante Android instalada para la prueba USB usa
`API_BASE_URL=http://127.0.0.1:8000` compilado en el APK. Crear e instalar otro
APK con `API_BASE_URL=https://backend-telemedicina.onrender.com` (o dejar el
valor predeterminado de `lib/core/config/api_config.dart`). El archivo
`mobile_telemedicina/android/app/google-services.json` debe estar presente al
compilar y coincide con el `applicationId` actual
`com.example.mobile_telemedicina`. Para distribuir una versión release se debe
configurar una firma propia; `android/app/build.gradle.kts` todavía usa la firma
de depuración en `release`.

El workflow `mobile_telemedicina/.github/workflows/ci.yml` restaura ese archivo
desde el secreto de repositorio GitHub `GOOGLE_SERVICES_JSON` antes de compilar
Android. Agregar como valor el contenido íntegro del archivo local
`google-services.json` en **Settings > Secrets and variables > Actions > New
repository secret**. El archivo permanece excluido de Git. El APK generado por
CI apunta explícitamente al backend HTTPS público; su firma actual sirve para
pruebas internas, no para publicar en Play Store.

Con el cable desconectado: iniciar sesión como PACIENTE, comprobar el registro
`POST /api/v1/tratamientos/dispositivos` con respuesta 201, abrir lista,
detalle, cronograma y avisos, disparar un ciclo del worker y confirmar la
notificación en Android. Al cerrar sesión, verificar la revocación del
dispositivo. La respuesta 200 de FCM confirma aceptación; la comprobación en
Android confirma la recepción visible.

## Referencias de plataforma

- Secret Files y Environment Groups: https://render.com/docs/configure-environment-variables
- Comandos de despliegue: https://render.com/docs/deploys
- Cron Jobs: https://render.com/docs/cronjobs
- Python en Render: https://render.com/docs/python-version
- FCM HTTP v1: https://firebase.google.com/docs/cloud-messaging/send/v1-api
- Firma y compilación Android: https://docs.flutter.dev/deployment/android
