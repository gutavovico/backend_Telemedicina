# Validación del contrato y pago canónicos existentes

Consulta de Neon del 2026-11-05, con conexión default_transaction_read_only=on,
SHOW transaction_read_only verificado y rollback al terminar. Sin migraciones
ni escrituras. La revisión consultada sigue en merge_cu18_asistencia_022.

VersionPlan 1 pertenece a Plan 1, número 1, con estas condiciones verificadas:

| Campo | Valor |
|---|---|
| Precio mensual / moneda / ciclo del catálogo | 125.00 / BOB / MENSUAL |
| Médicos / sedes / consultas | 10 / 5 / 100 |
| Servicios | RECETAS_DIGITALES, LISTA_ESPERA, SUBDOMINIO_PROPIO, INTEGRACIONES, LABORATORIO |
| Tarifas de excedentes | [] |
| Demora de pago | 7 días |

La suscripción MONTHLY/ACTIVE y su pago PAGADO tienen id_version_plan=1 e
id_plan_version=NULL. El pago de 125.00 BOB coincide exactamente con el precio
mensual y moneda de esa instantánea. No se obtiene la correspondencia por nombre.
Inicio y fin contratados: 2026-11-05T05:29:41.470415Z y
2026-12-05T05:29:41.470415Z. Pago: 2026-11-05T05:29:41.301274Z;
creación del pago: 2026-11-05T05:07:34.220473Z.

## Mapas según 022/023

| Mapa | ¿Lo requieren estos registros? | Motivo |
|---|---|---|
| subscription_version_map | No | Referencia canónica existente, legacy NULL |
| payment_version_map | No | Referencia canónica existente, legacy NULL |
| plan_version_map | No en el estado consultado | Cero referencias legacy en clinicas.plan_id y tenant_requests.plan_version_id |
| billing_anchor_map | Sí, para la suscripción existente | 022 exige el ancla original explícita, aunque las referencias sean canónicas |

Las fechas actuales no prueban el día original de anclaje. No se preparó un
mapa real ni se autorizó el día 5 para Neon. Falta evidencia o confirmación del
responsable contractual; sin ella la migración se detiene antes de mutar datos.

## Regresión aislada

tests/test_cu35_postgres.py reproduce esos importes, condiciones y fechas con
identificadores/cuentas ficticios. Compara todos los campos anteriores a la
migración en suscripción, pago y versión, y comprueba que no se duplica el pago.
No modifica una instantánea para preparar el fixture: se inserta con sus
condiciones definitivas, respetando el trigger de inmutabilidad de CU34.

Desde una plantilla en merge_cu18_asistencia_022, sin billing_anchor_map el
upgrade falla y conserva revisión/esquema. Con ancla EXCLUSIVA DE TEST explícita,
upgrade head llega a cu35_cu18_convergencia_023 conservando todos los campos
históricos, las referencias canónicas, estado PAGADO y fechas exactas; solo añade
los campos previstos de CU35. Esa prueba no acredita el ancla real del destino.

Resultado: nueve pruebas PostgreSQL CU35 aprobadas, incluyendo concurrencia y
worker idempotente. El clúster aislado se detuvo al terminar. No se modifican
migraciones ni la pasarela; pagos simulados, sin
verificación nueva en Stripe sandbox. El worker queda apagado localmente.
