CU35: integrar suscripciones CU31 con el catálogo versionado CU34

CU31 y CU35 usan versiones_plan.id como fuente común y conservan la versión exacta del contrato y de cada pago. El upgrade proporcional se aplica tras pago confirmado; el cambio programado y la cancelación respetan el cierre pagado. La renovación manual acepta la versión antes del checkout y la aplica al nuevo ciclo pagado.

Añade solicitudes aisladas por entidad, bloqueo clínico desde la cancelación y worker opt-in idempotente. 023 converge CU18/CU35 sin reescribir migraciones compartidas. La migración exige mapas explícitos y ancla original verificada; no relaciona versiones por nombre. No modifica la pasarela compartida ni añade datos/rutas de demo.

Validación: 159 pruebas backend aprobadas (5 PG omitidas ahí), selección PostgreSQL 77 aprobadas, cadena vacía y actualización poblada desde CU18, concurrencia y worker 0/2/0. Pagos simulados; no Stripe sandbox real. Frontend integrado: 292 aprobadas, 5 skips existentes y build aprobado.

Anclas de las dos suscripciones existentes resueltas por adopción explícita del responsable y aniversario verificado; mapa privado con día 5 para ambas. Diez regresiones PostgreSQL CU35 aprobadas, incluido cotejo completo del esquema y preservación de ambos historiales. Antes de desplegar: validar en copia Neon identificada, coordinar Stripe sandbox/webhook y Render Live SHA/rama. Worker false hasta migración/API y smoke tests. No se escribió en Neon. Véanse docs/REVISION-CU34-CU35.md y docs/DESPLIEGUE-CU35.md.

Decisión, estado actualizado y comandos de copia: docs/NEON-CU35-PREPARADO.md. Sin cambios funcionales ni reescritura de migraciones en este cierre.
