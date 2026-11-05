# Cierre técnico CU34/CU35 — 2026-11-05

## Base e integración

Backend origin/main: 04475fd973c1d1160da530d4838808493d2a7881.
Frontend origin/main: 2f364f331ca3b6b82fa78896e93e61ae953e4954.
SDD origin/main: fc64f9f05cbbce914971f4f582e7d6d742020e63.
Fetch completado. Se preservó el dispatcher Stripe compartido de main/04475fd sin alterarlo.
Conflictos resueltos al reaplicar el avance: app/main.py (dispatcher + router/worker
CU35) y tests/test_cu31_subscription_payments.py (helper firmado + test raíz
del equipo + renovación por aniversario). No hubo merge de ramas.
Respaldo por repositorio: backup/review-pre-cierre-20261105-cierre-cu35 y stash
«CU35 review preserved before main 20261105-cierre-cu35» (no se elimina).
Los worktrees originales feature/cu31-cu34-cu35 y SI2-Grupo3.md siguen intactos.

CU34 ya existe en main: no se duplica. Modelos globales Plan/VersionPlan en
app/modules/auth/models.py; CU31 y CU35 comparten versiones_plan.id mediante
id_version_plan en tenants.models. Se conservan las columnas legacy como evidencia.
CU35 usa subscription_changes (router, schemas, permisos, servicio, worker).
La web reutiliza /admin/suscripcion y su guard de administrador de entidad.
No cambia Flutter ni app/modules/payments, claves o configuración compartida Stripe.

Mensual BOB, Decimal/HALF_UP por segundos, aniversario con ancla original.
Upgrade aplica tras pago confirmado, sin mover el cierre; ajuste cero no cobra.
Renovación manual acepta y fija una versión publicada antes del checkout y la aplica
al próximo ciclo pagado. Cambio programado conserva destino exacto; sin pago queda
WAITING_RENEWAL y no extiende fechas. Cancelación efectiva bloquea clínica por
entidad y conserva login/facturación/datos. Se conserva como regresión interna,
sin incluirla en el guion de presentación. Worker false por defecto.

## Migraciones y datos

44 revisiones; única cabeza cu35_cu18_convergencia_023.
- 020/021 y toda revisión compartida quedan sin cambios.
- cu35_integracion_022 depende de cu06_servicios_clinica_021: solicitudes,
  aplicación de pagos, periodo y ancla; exige conciliación histórica explícita.
- merge_cu18_asistencia_022, recuperada en main/d952a29c, depende de
  cu18_asistencia_017 y cu06_servicios_clinica_021.
- 023 converge merge_cu18_asistencia_022 y cu35_integracion_022, sin DDL/DML.

No hay tablas solapadas entre CU18 y CU35. Columnas/tipos/nulabilidad/longitudes
CU18 coinciden con la inspección remota. No se certifican defaults, índices,
triggers o contenido clínico remoto por esa comprobación parcial.
020 tiene un backfill por nombre ya publicado: no se reescribe. El env Alembic
impide ejecutarlo si detecta versiones legacy antes de 020. Si ya se aplicó,
022 exige mapas explícitos por suscripción/pago legacy, valida condiciones y
retiene evidencia anterior. No se generan nuevas correspondencias por nombre.

Lectura Neon con transaction_read_only=on: revisión merge_cu18_asistencia_022;
una suscripción y un pago canónicos referencian versiones_plan.id=1, precio y
pago 125.00 BOB; periodo 2026-11-05T05:29:41.470415Z a
2026-12-05T05:29:41.470415Z. Referencias legacy NULL; FK RESTRICT verificadas.
No existen auditorías globales incompatibles con el CHECK nuevo al consultar.
No hay campo ancla ni eventos de auditoría de estas tablas que acrediten su origen.
El día 5 observado NO se aprueba como ancla original. billing_anchor_map verificado
sigue siendo obligatorio; la migración falla antes de alterar los datos sin él.
Renovar una suscripción existente sin ancla devuelve 409 en vez de inferirla.
No hubo escrituras Neon ni prueba de actualización en una copia Neon.
Identificadores técnicos de la conexión confirmados; nombre/tipo de rama y acceso
a una copia de prueba deben confirmarse en el panel. No se incluyen credenciales,
configuración local ni IDs de filas reales en los fixtures o mapas del PR.

## Verificación final

- Backend selección ampliada: 159 passed, 5 skipped (casos PG ejecutados aparte).
- Selección PostgreSQL: 76 passed, incluye 5 CU34 PG y 9 CU35 reales. Los totales
  comparten casos; no sumarlos como pruebas distintas.
- Cadena vacía -> head, CU35 anterior -> head y CU18 poblada -> head verificadas
  en PostgreSQL 17 existente, 127.0.0.1:55434. Se usaron bases cu34_test_*.
- Fixture poblado anónimo: un contrato/pago por 125 BOB. Sin ancla explícita,
  rollback mantiene revisión CU18 y esquema; con ancla ficticia explícita mantiene
  versión, importe, fechas y row_version. NO valida el ancla real de Neon.
- Concurrencia: misma clave una solicitud, claves distintas una pendiente,
  confirmación repetida aplica una vez, dos workers y repetición sin duplicados.
- Scheduler real opt-in solo dentro de test: antes/cierre/repetición 0/2/0;
  renovación pagada y cancelación al cierre, sin cobros del worker.
- Frontend: 292 passed, 5 skipped existentes; build production aprobado.
  Reintento fuera de la restricción de lectura de Windows; no se instalaron paquetes.
- OpenSpec doctor y validate --specs: CommandNotFoundException. CLI no disponible;
  validación formal pendiente, sin instalar herramientas por espacio.
- Pagos automatizados SIMULADOS. Checkout y entrega real de webhook Stripe sandbox
  pendientes de coordinar con el responsable. No se certifica Stripe ni producción.

## Entrega y publicación

Backend/SDD: Terrazas anterior es ancestro de main y se respalda con rama
backup/Terrazas-pre-cu35-20261105 antes de avanzarla a la entrega validada.
Frontend: origin/Terrazas NO es ancestro de main; conserva b4d23c4, de5f46d,
76ee538 y cambios locales Cypress ajenos. No se mueve ni reescribe Terrazas.
Su commit limpio queda en review/cu34-cu35-integrado, listo para publicarse con
ese nombre y abrir PR a main. Publicarlo como origin/Terrazas requiere conciliar
su historia mediante un paso autorizado posterior; no dar un push que fallará.

No se incluyen .env, copias, docs de configuración local, demo __cu35_demo,
controles de pago/reloj, cuentas manuales, capturas, temporales ni dependencias.
Sí se incluyen fixtures exclusivos de tests que nunca se cargan al iniciar app.
CONFIG-Y-CU18.md sigue solo local. Los PR incluyen las listas de archivos del
commit respectivo y no alteran los submódulos specs ni cambios Flutter.
Ver DESPLIEGUE-CU35.md y PR-CU35.md para pasos posteriores.

## Ampliación del fixture canónico

Se reconsultaron en solo lectura las condiciones completas de versiones_plan.id=1
y su correspondencia con el pago de 125.00 BOB. La regresión poblada conserva
todos los campos históricos anteriores a la migración, no solo precio y fechas.
No se requieren mapas de versión para esas dos filas; billing_anchor_map sigue
siendo obligatorio y pendiente de evidencia original. Véase VALIDACION-VERSION-1.md.
