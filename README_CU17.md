# CU17: Tratamientos médicos

Para publicar la API, el worker y el APK Android contra Render, seguir
`DEPLOY_CU17_RENDER.md`. La comprobación previa de solo lectura es
`python -m scripts.check_cu17_deploy`.
El Blueprint único para Render es `render.yaml`; el SQL PostgreSQL alternativo
para Neon es `deploy/cu17_neon_desde_backup01ab23cd.sql` y solo aplica a una
base en la revisión exacta indicada en su nombre, sin tablas CU17 previas.

La API está bajo `/api/v1/tratamientos`. El médico confirma los horarios de cada detalle de receta y el paciente registra las tomas. La receta firmada no se modifica. Las especificaciones CU17 del submódulo `specs` permanecen locales hasta que el equipo decida publicarlas por separado.

## Preparación

1. Instalar las dependencias de `requirements.txt` y revisar las variables CU17 de `.env.example`.
2. Antes de ejecutar la migración en un entorno compartido, verificar en solo lectura sus tablas y la revisión Alembic. Aplicar la migración como parte del despliegue coordinado: `python -m alembic upgrade head`. La migración es aditiva y crea permisos para `MEDICO` y `PACIENTE`; no elimina historia clínica en el downgrade.
3. Ejecutar el proceso de recordatorios por separado de la API: `python -m scripts.run_cu17_notificaciones --interval 60`. Para una sola ejecución: `python -m scripts.run_cu17_notificaciones --once`. El proceso debe estar supervisado para reiniciarse tras fallos.

La bandeja web funciona sin proveedor push. Para dispositivos móviles se configura FCM HTTP v1 con `CU17_FCM_PROJECT_ID`, `CU17_FCM_SERVICE_ACCOUNT_FILE` y `CU17_DEVICE_TOKEN_KEY` (clave Fernet protegida y estable); el servidor requiere acceso de red al proveedor. Sin esa configuración, el registro de dispositivos responde 503 y el registro de tomas continúa disponible. Nunca se guardan tokens de dispositivo en texto claro ni se imprimen en logs.

Para Android, copiar `google-services.json` en `mobile_telemedicina/android/app/` y la clave privada de la cuenta de servicio en `backend/.secrets/` o en un gestor de secretos del servidor. Ambas rutas están excluidas de Git. `CU17_FCM_SERVICE_ACCOUNT_FILE` debe contener la ruta absoluta del archivo privado en el entorno donde corre la API y el worker. `CU17_DEVICE_TOKEN_KEY` debe generarse una sola vez y conservarse entre despliegues: cambiarla impide descifrar los dispositivos registrados. El cliente Android registra el identificador de instalación FCM de una sesión paciente verificada, lo actualiza al cambiar y lo revoca al cerrar sesión.

La anulación normal de CU16 suspende el plan en la misma transacción con el usuario que anuló la receta. Para reconciliar anulaciones realizadas fuera de CU16, configurar `CU17_SYSTEM_USER_IDS_JSON` como un mapa de cada `id_clinica` al ID de una cuenta activa de esa clínica con rol activo `SISTEMA`. Sin cuenta válida, el worker informa la clínica pendiente; las acciones y avisos del plan permanecen bloqueados por el estado efectivo de la receta.

## Pruebas locales

En PowerShell, desde `backend`:

```powershell
$env:STORAGE_BACKEND = 'local'
.\.venv\Scripts\python.exe -m pytest tests/test_cu17_tratamientos.py tests/test_cu17_avisos.py tests/test_cu17_migration.py tests/test_cu16_recetas.py -q
```

Las pruebas usan bases SQLite aisladas y un proveedor push simulado. La migración PostgreSQL y una entrega real FCM deben verificarse en el entorno de despliegue con su configuración correspondiente.
