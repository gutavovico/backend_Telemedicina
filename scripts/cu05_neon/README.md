# CU05NEONVERIFYV1 — verificación en Neon

La prueba usó el Neon cargado por `backend_Telemedicina/.env`, con la app y autenticación reales. No se ejecutaron migraciones, `create_all` ni cambios de esquema. `scripts/run_cu05_neon_verify.py` creó solo el marcador `CU05NEONVERIFYV1` y ejecutó las rutas CU05 mediante `TestClient`. No usa el lanzador READ ONLY ni reemplaza la configuración CU16. La limpieza [limpiar.sql](limpiar.sql) está preparada, **no ejecutada**.

## Fixture persistido

| Objeto | Cantidad | IDs observados |
|---|---:|---|
| Clínicas A/B | 2 | 9, 10 |
| Roles y usuarios | 6 y 6 | usuarios 45–50 |
| Médicos A/B | 2 | 13, 14 |
| Pacientes A/B | 2 | 28, 29 |
| Citas A | 2 | 29 (CANCELADA), 30 (CONFIRMADA sin `hora_fin`) |
| Horarios recurrentes | 2 | 17, 18; domingo, servicio 1 |
| Bloqueos | 2 | 1, 2; ambos `LIBERADO` |
| Auditoría CU05 | 8 | 2 altas de horario y 3 acciones por bloqueo |

Fechas de los escenarios: **2026-10-04** (horario y ciclo del bloqueo), **2026-10-11** (cancelada), **2026-10-18** (sin `hora_fin`). Servicio 1: 08:00–13:00, 30 minutos. No se cambió CU22N26V1 ni ninguna cuenta o cita previa.

| Rol | Correo sintético |
|---|---|
| ADMIN A | `cu05neonverifyv1-admin-a@example.com` |
| Médico A | `cu05neonverifyv1-medico-a@example.com` |
| Recepción A | `cu05neonverifyv1-recepcion-a@example.com` |
| Paciente A | `cu05neonverifyv1-paciente-a@example.com` |
| ADMIN B | `cu05neonverifyv1-admin-b@example.com` |
| Médico B | `cu05neonverifyv1-medico-b@example.com` |

Contraseña común, **solo de estas cuentas**: `Cu05-Neon-2026!`. `LoginRequest` aceptó los correos `example.com`; el script generó el hash con `app.core.security.hash_password`. No contiene ni muestra secretos de `.env` o JWT.

## Repetición segura de lectura API

Desde `backend_Telemedicina`:

```powershell
& '..\.venv\Scripts\python.exe' -m scripts.run_cu05_neon_verify
```

El script comprueba el marcador antes de reutilizarlo. Con el fixture completo, no duplica clínicas, cuentas, horarios, bloqueos ni citas. Las peticiones de rechazo 403/404 tampoco escriben. Si encuentra un estado parcial o referencias inesperadas, se detiene.

## Un recorrido web manual

1. Detén en **su propia terminal** el lanzador `run_cu22_neon_readonly.py` que actualmente ocupa el puerto 8000. No lo uses para esta prueba de escritura. Desde `backend_Telemedicina`, arranca `& '..\.venv\Scripts\python.exe' -m scripts.run_cu05_neon`. El proceso escucha solo en `127.0.0.1:8000` y conserva `.env` y CU16.
2. Angular ya puede estar en `http://localhost:4200`. Si no está, desde `frontend_Telemedicina` ejecuta `npm.cmd start -- --host localhost --port 4200`. Abre `http://localhost:4200/login` en ventana privada; comprueba en Network que `/auth/me` y `/appointments/agenda/*` van a `http://localhost:8000`.
3. Entra como Médico A y abre `http://localhost:4200/agenda`. Selecciona servicio 1 y **2026-10-04**: 10 slots disponibles y horario dominical activo. En **2026-10-11**, la cita cancelada no reduce los 10 slots. En **2026-10-18**, deben verse `citas_verificadas=false` y el aviso de `hora_fin`; ningún slot libre.
4. En otra ventana privada, entra como Recepción A. Selecciona Médico A, servicio 1 y esas tres fechas; espera los mismos resultados. El médico de B no debe aparecer como opción autorizada de A. En una tercera ventana privada, entra como ADMIN A: ve los dos bloqueos del fixture como `LIBERADO`, sin poder crear horarios. ADMIN B no ve los bloqueos de A. Paciente A no debe acceder a Agenda.
5. Para comprobar nuevamente el ciclo de escritura en la interfaz, usa **otra fecha futura válida** y un intervalo libre alineado con servicio 1. El médico solo puede solicitar para mañana según la fecha boliviana; Recepción puede usar otra fecha. La solicitud pasa a `PENDIENTE`, ADMIN A la aprueba y Médico A o Recepción A la libera. Esto añade nuevas filas marcadas solo si el motivo lleva `CU05NEONVERIFYV1`; si haces esa prueba, la limpieza preparada abortará hasta revisar y ampliar sus guardas para esas filas. Para conservar la limpieza exacta actual, limita el recorrido a las lecturas de los pasos 3 y 4: el ciclo de escritura ya se probó por API.

En la sesión que ejecutó este verificador no se dispuso de control de navegador.
Posteriormente el usuario informó que completó satisfactoriamente el recorrido
manual web CU05 contra Neon; esa revisión visual no fue ejecutada por el
verificador API. Angular y el backend son repositorios separados. Las reservas
CU25 siguen desconectadas de la disponibilidad CU05; este recorrido no valida
su integración. Móvil permanece sin compilar ni probar.

## Limpieza

`limpiar.sql` solo acepta las cantidades, relaciones y estados documentados. Revisa sus guardas y ejecútalo **completo** en SQL Editor únicamente al terminar la prueba. Si aborta, ejecuta `ROLLBACK` si la sesión quedó en error y revisa referencias; no uses `CASCADE`, fechas amplias ni IDs fijos para forzar borrados. Las secuencias PostgreSQL pueden conservar huecos después de insertar o borrar el fixture. La limpieza no toca registros CU22N26V1.
