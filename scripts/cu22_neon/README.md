# CU22/CU27: revisión web con Neon y datos sintéticos

**Población realizada; no volver a ejecutar `poblar.sql` en esta base.** El usuario confirmó que el conjunto CU22N26V1 fue insertado en Neon. Una lectura posterior en transacción `READ ONLY` confirmó las ocho cuentas originales, sus roles y clínicas, 16 citas y 10 consultas; las ocho direcciones de destino `example.com` estaban libres. `LoginRequest.correo` usa `EmailStr`: el esquema real aceptó localmente las ocho direcciones `example.com` y rechazó las ocho `example.invalid`, sin realizar login ni enviar correos. El cambio de correos está preparado en `actualizar_correos.sql`, **aún no ejecutado**. No se ejecutó `limpiar.sql`. Ningún archivo contiene secretos del `.env`; el hash del SQL corresponde exclusivamente a la contraseña de demostración indicada abajo.

## Arranque y efectos

`app/main.py` importa los routers y su `lifespan` valida claves CU16. No invoca `create_all`, Alembic ni semillas. `scripts/run_cu22_neon_readonly.py` carga el mismo `app.main:app`, la configuración Neon del backend desde `.env` y el `lifespan` real. No genera ni sustituye claves CU16: si falta o es inválida su configuración, el arranque falla antes de servir. Una comprobación local de configuración validó CU16 sin mostrar valores; deberá seguir siendo válida al arrancar. Conserva las claves públicas históricas requeridas para verificar recetas anteriores. El lanzador marca las conexiones del `engine` compartido como `READ ONLY`, rechaza un host que no sea Neon y exige CORS para `http://localhost:4200`. **Es exclusivamente para pruebas de lectura de Analytics.** `READ ONLY` no aísla criptográficamente las rutas CU16, que siguen registradas; no usar este proceso para recetas, creación de citas, agenda ni otras rutas que escriben. Tampoco usar `scripts/run_cu22_local.py`: sustituye Neon por SQLite. Este ajuste se revisó sin arrancar el servidor ni conectar a Neon.

`POST /auth/login`, `GET /auth/me`, catálogo, opciones, consulta y exportación leen la BD; login crea JWT localmente, sin insertarlo. `POST /auth/logout` **sí** incrementa `usuarios.token_version` e inserta en `token_blacklist`: con el lanzador de solo lectura fallará y no revocará el token. Usa sesiones privadas separadas y ciérralas para descartar tokens locales durante esta revisión. No pulses acciones de interpretación o dictado con datos existentes de Neon: llamarían a Groq. El usuario ya completó las pruebas web con los datos existentes; falta la prueba con el conjunto sintético.

La conexión directa de auditoría usó SSL y transacciones de solo lectura. No recomendar `PGOPTIONS` para este pooler: el parámetro de arranque `options` falló; la sesión de solo lectura se aplica después de conectar.

### Terminal 1, backend Neon de solo lectura

```powershell
Set-Location 'C:\Users\hp\Desktop\si2G3-4\Telemmedicina-SDD\backend_Telemedicina'
& '..\.venv\Scripts\python.exe' .\scripts\run_cu22_neon_readonly.py
```

### Terminal 2, Angular development

`environment.ts` apunta a `http://localhost:8000`; producción conserva Render. `ng serve` usa configuración development; `node_modules` ya está presente. El CORS cargado desde `.env` permite `http://localhost:4200`, no presupongas que permite `127.0.0.1:4200`.

```powershell
Set-Location 'C:\Users\hp\Desktop\si2G3-4\Telemmedicina-SDD\frontend_Telemedicina'
npm.cmd start -- --host localhost --port 4200
```

Abrir `http://localhost:4200/login` y luego `http://localhost:4200/analitica`. Detener ambos procesos con **Ctrl+C**. Si 8000 o 4200 están ocupados, detén el proceso anterior en su propia terminal antes de iniciar estos comandos. Verifica en Network que las peticiones usen `http://localhost:8000`, no Render ni SQLite.

### Primero: datos existentes, sin población

Antes de añadir el fixture se observaron dos usuarios existentes que satisfacían de forma agregada usuario/rol/clínica activos y ADMIN. No se conocen aquí sus contraseñas y no se cambian. Para identificar una cuenta legítima existente, esta lectura no muestra hashes:

```sql
SELECT u.correo, u.id_clinica
FROM usuarios u JOIN roles r ON r.id_rol=u.id_rol
JOIN clinicas c ON c.id_clinica=u.id_clinica
WHERE lower(u.estado)='activo' AND lower(r.estado)='activo'
  AND lower(c.estado)='activo'
  AND upper(r.nombre) IN ('ADMIN','ADMINISTRADOR','ADMINISTRACION')
  AND (r.id_clinica IS NULL OR r.id_clinica=u.id_clinica);
```

Esos resultados eran una referencia **anterior a la población**: una clínica devolvía 5 citas y la lectura global tenía 7 citas/0 consultas. Ya no describen el estado actual. Para el fixture usa los conteos de julio indicados abajo. Prueba período, filtros, columnas, agrupación por fecha, orden, página 1 con tamaño 2 y páginas siguientes. Descarga PDF, XLSX, CSV y HTML, revisa nombre, MIME, contenido y todas las filas filtradas. Ausentismo debe figurar **No disponible**, nunca 0. Evita Enviar, Aplicar filtros y micrófono si no deseas enviar solicitudes a Groq.

## SQL Editor de Neon: corrección manual de los ocho correos

1. Selecciona el mismo proyecto, rama y base donde ya se insertó CU22N26V1. No ejecutes `poblar.sql` ni `reparar_secuencia_clinicas.sql` de nuevo.
2. Ejecuta **todo** `verificar.sql` como lectura previa. Debe mostrar 2 clínicas, 8 roles, 8 usuarios, 16 citas y 10 consultas; el desglose de correos debe ser **8 originales / 0 corregidos / 8 relaciones coherentes**. Los totales de julio deben ser 16/10 si no hay datos ajenos. Si algo difiere, detente y revisa con el equipo.
3. Copia y ejecuta **completo** `actualizar_correos.sql` en una sola ejecución. Su transacción bloquea escrituras concurrentes sobre clínicas, roles y usuarios, verifica cada cuenta y cada destino, y actualiza solo `usuarios.correo` para ocho direcciones exactas. Un error aborta el cambio; si el SQL Editor deja la transacción abierta en estado fallido, ejecuta `ROLLBACK` antes de continuar. No ejecutes el archivo por partes.
4. Ejecuta otra vez `verificar.sql`. Espera **0 originales / 8 corregidos / 8 relaciones coherentes**, con los mismos conteos de 2 clínicas, 8 roles, 8 usuarios, 16 citas, 10 consultas y 16/10 en julio. Si los números difieren, no intentes una segunda actualización ni borres datos: revisa primero el estado.
5. Inicia o reinicia el backend Neon `READ ONLY` y Angular con los comandos anteriores. En una ventana privada nueva, entra en `http://localhost:4200/login` con `cu22n26v1-admin-a@example.com` y la contraseña sintética indicada abajo. Comprueba `/analitica` en julio. Para B usa otra ventana privada o cierra la primera; `logout` escribe y no funciona en este lanzador.

`actualizar_correos.sql` **no se ha ejecutado** en Neon. Hasta hacerlo, el login de estas cuentas seguirá rechazando `example.invalid` antes de comprobar la contraseña. `limpiar.sql` reconoce ambos dominios y debe usarse solo tras completar las pruebas y revisar referencias; si aborta, no fuerces borrados ni uses `CASCADE`.

### Conjunto ya insertado

Marcador exclusivo `CU22N26V1`, período **2026-07-01 a 2026-07-31**. El conjunto contiene 2 clínicas, 8 roles propios (ADMIN, MEDICO, RECEPCION, PACIENTE por clínica), 8 usuarios, 2 médicos, 4 pacientes, 2 especialidades, 2 asociaciones médico-especialidad, 4 historias, 16 citas y 10 consultas. Los IDs se generaron mediante `RETURNING`; la actualización de correos no los modifica ni toca contraseñas o datos relacionados. `tipo_consulta` y `modalidad` coinciden (`PRESENCIAL` o `TELEMEDICINA`). No se crean tablas, servicios ni horarios.

La contraseña **únicamente sintética** de las ocho cuentas es `Cu22NeonDemo!2026`; el hash bcrypt incluido en `poblar.sql` fue generado y verificado localmente mediante `app.core.security.hash_password`, no inventado ni leído de Neon. Los siguientes correos serán utilizables **después** de ejecutar `actualizar_correos.sql` y confirmar el resultado:

| Clínica | ADMIN | Médico | Recepción | Paciente |
| --- | --- | --- | --- | --- |
| A | `cu22n26v1-admin-a@example.com` | `cu22n26v1-medico-a@example.com` | `cu22n26v1-recepcion-a@example.com` | `cu22n26v1-paciente-a@example.com` |
| B | `cu22n26v1-admin-b@example.com` | `cu22n26v1-medico-b@example.com` | `cu22n26v1-recepcion-b@example.com` | `cu22n26v1-paciente-b@example.com` |

| Clínica / filtro en julio | Citas | Cancelaciones | Encuentros | Pacientes únicos atendidos | Grupos por fecha |
| --- | ---: | ---: | ---: | ---: | ---: |
| A, sin filtro | 12 | 4 | 8 | 2 | 4 |
| A, `estado=CANCELADA` (reportes de citas) | 4 | 4 | — | — | 4 |
| A, `modalidad=PRESENCIAL` | 8 | 4 | 4 | 1 | 4 |
| A, `modalidad=TELEMEDICINA` | 4 | 0 | 4 | 1 | 4 |
| B, sin filtro | 4 | 2 | 2 | 2 | 2 |
| B, `modalidad=PRESENCIAL` | 2 | 1 | 1 | 1 | 2 |
| B, `modalidad=TELEMEDICINA` | 2 | 1 | 1 | 1 | 2 |

En A, las fechas 02, 07, 14 y 21 de julio tienen cada una 3 citas, 1 cancelación, 2 encuentros y 2 pacientes atendidos. El global de pacientes únicos es **2**, aunque la suma de los grupos sea 8. En B, 03 y 17 de julio tienen 2 citas, 1 cancelación, 1 encuentro y 1 paciente atendido por fecha. Con agrupación `fecha`, página de tamaño 2 y orden descendente, A ocupa dos páginas (21/14, luego 07/02); B una. Exportar desde la primera página debe incluir los 4 grupos de A o los 2 de B. Los filtros `id_medico` e `id_especialidad` se eligen en Opciones; sus IDs son generados, no están fijados en la guía. Cada clínica debe ver solo su médico y su especialidad sintéticos.

No se duplica una consulta por cita: el esquema físico no impone unicidad, pero el flujo HCE pone la cita en `FINALIZADA` tras crear la primera y rechaza otra. Por ello esta población fiel al flujo deja 10 filas de consulta para 10 citas con consulta. La comprobación de `COUNT(DISTINCT id_cita)` ante duplicados requiere un escenario clínico autorizado distinto; no se simula aquí.

## Discrepancias que debe decidir el equipo

- `GENERAL/PRESENCIAL`: hay 3 citas antiguas con esos valores. `seed_demo_data.py` escribió `GENERAL` junto a servicio Medicina General y `modalidad=PRESENCIAL`; ese `GENERAL` describe aparentemente el **tipo de atención**, mientras `PRESENCIAL` describe el canal. En cambio, el contrato de CU25 describe `tipo_consulta` como `PRESENCIAL` o `TELEMEDICINA` y su servicio copia ese valor a ambos campos. La regla actual de Analytics compara ambos como modalidades y produce `CONFLICTO`. Es un conflicto **de clasificación vigente**, no prueba de contradicción clínica ni un efecto de CU05. Acordar semántica y reglas futuras por separado; no corregir esos registros ahora.
- Una relación cita/médico/usuario tiene clínica nula y queda fuera del ámbito ADMIN; `citas.id_clinica` y `usuarios.id_clinica` coinciden en las otras relaciones observadas. Un paciente con cita de clínica tiene `pacientes.id_clinica` nula, y otra relación tiene ambas nulas. Analytics no filtra por paciente-clínica según contrato. Mantener la decisión general paciente-clínica y atribución de citas para después del merge.
- Un usuario referencia una clínica inexistente. La consulta de clínica activa de Analytics lo rechazaría; no puede ampliar acceso a reportes. Revisar integridad referencial de `usuarios` más adelante, sin editar ese registro aquí.
- Neon tiene `medicos.id_clinica` actualmente; el informe anterior de CU05 que la describía ausente quedó desactualizado. `citas.id_clinica` existe en Neon y no en el ORM de citas. No cambia los reportes actuales, pero merece reconciliación después del merge.

## CU05: diagnóstico y plan pendiente

La copia disponible no incluye el contrato histórico completo de CU05. Sí están el complemento `openspec/contracts/agenda-local-verification.md`, el cambio `verify-cu05-local-main` y `VERIFICACION-CU5.md`. La tarea **1.6, interacción real en navegador, sigue abierta**. El informe registra pruebas SQLite y Angular, pero no prueba CU05 en Neon. El informe decía que `medicos.id_clinica` faltaba; la lectura viva actual confirma que ya existe.

| Criterio | Implementación actual | Evidencia disponible | Pendiente e impacto en CU22/CU27 |
| --- | --- | --- | --- |
| Días y duración | `horarios_medicos.dia_semana` activa un servicio global con horas/duración fijas; no edita horas por médico. Neon tiene 3 servicios, 8 horarios y `TIME` para servicios/bloqueos. | Pruebas SQLite de días, slots y servicio; metadatos Neon vivos. | Confirmar en navegador y Neon. No cambia agregados de reportes. |
| Horas inválidas y solapes | Pydantic/servicio validan fecha, límites y múltiplos; el servicio detecta solape. Neon tiene `CHECK` y exclusión GiST para bloqueos pendientes/aprobados. | Pruebas SQLite; restricciones Neon leídas, no ejercidas. | Probar rechazo/concurrencia en rama Neon; no afecta conteos CU22 salvo citas nuevas. |
| Bloquear, aprobar, liberar | Médico/Recepción solicitan; solo ADMIN aprueba/rechaza; Médico/Recepción liberan. `PENDIENTE` y `APROBADO` restan slots. | HTTP aislado: solicitud 201, aprobación 200, liberación 200 y 10→8→10 slots; sin navegador Neon. | Validar roles, estados, avisos y liberación en Neon. Reportes siguen contando citas sin inferir ausentismo. |
| Disponibilidad al reservar | `/appointments/agenda/disponibilidad` considera horario, bloqueos y citas. **`/citas/horarios-disponibles` usa una lista fija y solo mira citas**, sin consultar CU05; crear cita tampoco consulta horarios/bloqueos CU05. Flutter usa esa ruta de citas. | Evidencia de código; no hay prueba de integración de reserva. | **Bloquea el cierre funcional de CU05** si el criterio exige que el bloqueo impida reservar. Requiere acuerdo y corrección posterior en CU25/reserva; no alterar Analytics. |
| Interfaces | Angular implementa gestión y revisión ADMIN; móvil tiene reserva de citas pero no interfaz CU05 de horarios/bloqueos. | Código y pruebas Angular del informe; revisión visual CU05 pendiente. | Confirmar alcance móvil y recorridos reales. No se atribuye `GENERAL/PRESENCIAL` a CU05. |

### Plan funcional CU05 en una rama Neon de pruebas, **sin ejecutar ahora**

1. Crear después una **rama de Neon separada** con el esquema actual; configurar el backend de pruebas para esa rama. Preparar allí las cuentas sintéticas ADMIN, Médico, Recepción y Paciente de dos clínicas; no usar cuentas del equipo. Capturar IDs generados y un marcador exclusivo CU05 en cualquier solicitud de bloqueo. La rama permite limpiar eliminándola al terminar, incluidos auditoría, notificaciones y tokens, sin borrar registros del equipo.
2. Elegir el día siguiente según Bolivia (`UTC−04:00`) y un médico sintético de A. Médico o Recepción activa el servicio global 1 para ese día de semana: 08:00–13:00, 30 minutos. Esperar 10 slots. Repetir alta: 409; desactivar: 0 disponibles; reactivar: 10. Intentar día fuera de 1–7 y horarios inválidos: 422.
3. Médico solicita bloqueo 10:00–11:00 para mañana: `PENDIENTE` y 8 slots libres; intentar hoy, 10:15–10:45 y un bloqueo solapado: 422/409 según caso. Recepción no aprueba (403); ADMIN A aprueba, verifica citas afectadas/avisos y 8 slots; Médico o Recepción libera y vuelve a 10. ADMIN B no accede al bloqueo de A. Paciente no gestiona agenda.
4. Comparar **ambas** rutas de disponibilidad y la pantalla real de reserva antes, durante y después del bloqueo. Actualmente se espera divergencia: `/citas/horarios-disponibles` puede anunciar 10:00 como libre y `POST /citas` puede aceptarlo si no hay otra cita. No crear una cita de prueba sobre el bloqueo hasta acordar cómo contener ese defecto; registrar la evidencia y probar la corrección posteriormente.
5. Probar Angular en escritorio y pantalla estrecha, mensajes de error, filtros, actualización, sesión y navegación. Probar por separado móvil cuando haya Flutter; las pruebas web no lo sustituyen. Al finalizar, detener procesos y **eliminar la rama de pruebas** tras revisar resultados. No ejecutar este plan sobre la rama compartida ni usar `limpiar.sql` de CU22 para residuos CU05.

Para cerrar CU05 faltan: contrato histórico o decisión de alcance, prueba funcional Neon de GiST/roles/avisos, recorrido visual real, integración de disponibilidad con reserva y pruebas posteriores de las correcciones. Ninguna tarea marcada ni esta inspección estática lo declara terminado.
