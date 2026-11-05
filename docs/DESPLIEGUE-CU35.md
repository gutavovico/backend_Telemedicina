# Migración y activación CU35 (no ejecutadas en la base compartida)

## Requisitos antes del despliegue

1. Aprobar contrato SDD y PR backend; coordinar autodeploy/ventana con el equipo.
2. Confirmar proyecto/rama Neon y crear copia identificada para prueba, sin usar
   production. Capturar revisión y esquema con scripts/inspect_cu35_target.py.
3. Recuperar del responsable o evidencia contractual el ancla mensual original de
   cada suscripción existente. No usar fecha_inicio como sustituto. El destino
   observado requiere billing_anchor_map; no requiere mapa legacy al estar NULL.
4. Si existen datos legacy, preparar snapshots fieles y mapas subscription_version_map,
   payment_version_map por fila, y plan_version_map para referencias antiguas.
   Mantener esa evidencia fuera de Git. No ejecutar 020 con backfill por nombre.
5. Probar la actualización en la copia, FKs, condiciones/pagos/fechas conservados,
   concurrencia y worker repetido. No stamp ni downgrade automático.

023 deja head único cu35_cu18_convergencia_023. Desde merge_cu18_asistencia_022
se aplica CU35/022 y luego 023. Desde cu35_integracion_022 se aplica la rama CU18
faltante y luego 023. Ambas rutas se probaron localmente, sin reescribir revisiones.

## Comando de migración (solo tras verificar copia y aprobar los mapas)

Carpeta: raíz del backend de entrega. El .env pertenece a esa raíz; confirmar que
DB_* de la terminal no lo sobrescriban. No imprimir claves ni URL autenticada.
El siguiente ejemplo solicita la ruta de un JSON PRIVADO con un objeto que
relaciona ID de suscripción y día original verificado (entero 1..31):

```powershell
$cu35Python='C:/Users/hp/Desktop/si2G3-5/Telemmedicina-SDD/backend_Telemedicina/.venv-cu34/Scripts/python.exe'
& $cu35Python scripts/inspect_cu35_target.py --env-file .env
$cu35MapPath=Read-Host 'Ruta local del mapa de anclas revisado'
$cu35AnchorJson=Get-Content -Raw -LiteralPath $cu35MapPath
& $cu35Python -m alembic -x "billing_anchor_map=$cu35AnchorJson" upgrade head
```

No ejecutar estos comandos de upgrade sobre la base compartida en esta entrega.
Sin filas previas no se requiere mapa. Para legacy añadir los mapas revisados con
sus respectivas opciones -x; no improvisar correspondencias para superar errores.
Tras upgrade verificar alembic current, las FKs RESTRICT a versiones_plan,
subscription_changes y snapshots/fechas/importe de cada registro migrado.

## Pruebas locales reproducibles

Usar checkout/copia de código SIN .env; los runners lo exigen. No retirar la
configuración del worktree de revisión ni saltarse esa protección. Dependencias
Python/Node existentes; no es necesario instalarlas para los checks realizados.

```powershell
# Desde la raíz de la copia de backend sin .env:
& $cu35Python scripts/run_subscription_checks.py -q
$env:CU35_LOCAL_DATABASE_URL='postgresql+psycopg2://cu34@127.0.0.1:55434/cu34_test_cu35_final'
& $cu35Python scripts/check_cu35_postgres.py test tests/cu34/test_catalogo.py tests/test_cu35_postgres.py -q
```

La segunda orden usa las plantillas locales de esta sesión: cu34_test_cu35_base,
cu34_test_cu35_review_base, cu34_test_cu35_cu18_base y cu34_test_cu35_final.
En otro equipo crear bases aisladas/plantillas con sus revisiones esperadas antes
de ejecutar; los tests clonan bases y las eliminan. Nunca usar nombres o hosts remotos.

Frontend, desde su raíz: npm run test:vitest; npm run build. En esta PC se usó
--runner-config tmp/vitest-local.config.mjs --coverage=false para limitar workers
(config local excluido del PR). Comprobar CLI OpenSpec en SDD antes de aprobarlo.

## Orden de despliegue y worker

SDD -> backend aprobado -> respaldo/copia y migración validada -> API con worker
false -> frontend compatible -> smoke tests -> activar worker de forma explícita
con SUBSCRIPTION_CYCLE_WORKER_ENABLED=true en el entorno de despliegue migrado.
El worker procesa cada 60 segundos; repetir el cierre no cobra ni duplica cambios.
No activar en equipos locales conectados a la base compartida. Para ejecución
única: python -m app.modules.tenants.subscription_changes.worker --apply, SOLO
tras confirmar destino y autorización; no es un comando de inspección.

Coordinar checkout/webhook Stripe sandbox con el responsable sin cambiar la
pasarela compartida. Los pagos de regresión son simulados. Cancelación permanece
como prueba interna, fuera del guion de presentación. Revisar Render Live SHA y
rama, y autodeploy frontend, antes de coordinar la ventana. No se garantiza
compatibilidad productiva sin validar copia, mapa real, configuración y sandbox.
