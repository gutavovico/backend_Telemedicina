-- CU22N26V1: solo SELECT. El conjunto ya existe en Neon; no volver a poblar.
-- Antes/despues de actualizar correos: los conteos clinicos deben ser iguales.

SELECT (SELECT count(*) FROM citas
        WHERE fecha_cita BETWEEN DATE '2026-07-01' AND DATE '2026-07-31') AS citas_julio_total,
       (SELECT count(*) FROM consultas
        WHERE fecha_consulta >= TIMESTAMP '2026-07-01'
          AND fecha_consulta < TIMESTAMP '2026-08-01') AS consultas_julio_total;
-- Con CU22N26V1 insertado: 16/10 si nadie agregó otros datos en julio.

SELECT 'clinicas' AS objeto, count(*) AS filas FROM clinicas WHERE nit IN ('CU22N26V1-A','CU22N26V1-B')
UNION ALL SELECT 'roles', count(*) FROM roles WHERE descripcion = 'CU22N26V1'
UNION ALL SELECT 'usuarios', count(*) FROM usuarios WHERE correo ~
    '^cu22n26v1-(admin|medico|recepcion|paciente)-(a|b)@example[.](invalid|com)$'
UNION ALL SELECT 'medicos', count(*) FROM medicos WHERE matricula_profesional LIKE 'CU22N26V1-%'
UNION ALL SELECT 'pacientes', count(*) FROM pacientes WHERE ci LIKE 'CU22N26V1%'
UNION ALL SELECT 'especialidades', count(*) FROM especialidades WHERE nombre LIKE 'CU22N26V1-%'
UNION ALL SELECT 'medico_especialidad', count(*) FROM medico_especialidad me
    JOIN medicos m ON m.id_medico = me.id_medico WHERE m.matricula_profesional LIKE 'CU22N26V1-%'
UNION ALL SELECT 'historias_clinicas', count(*) FROM historias_clinicas WHERE numero_historia LIKE 'CU22N26V1-%'
UNION ALL SELECT 'citas', count(*) FROM citas WHERE notas LIKE 'CU22N26V1:%'
UNION ALL SELECT 'consultas', count(*) FROM consultas WHERE motivo_consulta LIKE 'CU22N26V1:%'
ORDER BY objeto;
-- Esperado tras poblar: 2, 8, 8, 2, 4, 2, 2, 4, 16, 10 respectivamente.

-- Antes del UPDATE: 8 originales/0 corregidos. Despues: 0/8.
-- Las ocho filas deben pertenecer a sus roles y clinicas sinteticas.
SELECT count(*) FILTER (WHERE u.correo ~ '@example[.]invalid$') AS correos_originales,
       count(*) FILTER (WHERE u.correo ~ '@example[.]com$') AS correos_corregidos,
       count(*) FILTER (WHERE c.nit = 'CU22N26V1-' || upper(substring(u.correo from '-(a|b)@'))
                         AND r.nombre = upper(substring(u.correo from '^cu22n26v1-(admin|medico|recepcion|paciente)-'))
                         AND r.descripcion = 'CU22N26V1'
                         AND r.id_clinica = u.id_clinica) AS relaciones_coherentes
FROM usuarios u
LEFT JOIN clinicas c ON c.id_clinica = u.id_clinica
LEFT JOIN roles r ON r.id_rol = u.id_rol
WHERE u.correo ~ '^cu22n26v1-(admin|medico|recepcion|paciente)-(a|b)@example[.](invalid|com)$';
-- Esperado antes: 8/0/8; despues: 0/8/8. Otro estado exige detenerse.

WITH scoped AS (
    SELECT cl.nit AS clinica, c.id_cita, c.id_paciente, c.fecha_cita,
           upper(c.estado) AS estado, upper(c.tipo_consulta) AS tipo_consulta,
           upper(c.modalidad) AS modalidad
    FROM citas c JOIN clinicas cl ON cl.id_clinica = c.id_clinica
    WHERE cl.nit IN ('CU22N26V1-A','CU22N26V1-B') AND c.notas LIKE 'CU22N26V1:%'
), encounters AS (
    SELECT DISTINCT s.clinica, s.id_cita, s.id_paciente
    FROM scoped s JOIN consultas q ON q.id_cita = s.id_cita
    WHERE q.motivo_consulta LIKE 'CU22N26V1:%'
)
SELECT s.clinica, count(DISTINCT s.id_cita) AS citas,
       count(DISTINCT s.id_cita) FILTER (WHERE s.estado = 'CANCELADA') AS cancelaciones,
       count(DISTINCT e.id_cita) AS encuentros,
       count(DISTINCT e.id_paciente) AS pacientes_unicos_atendidos
FROM scoped s LEFT JOIN encounters e ON e.clinica = s.clinica AND e.id_cita = s.id_cita
GROUP BY s.clinica ORDER BY s.clinica;
-- Esperado A: 12,4,8,2; B: 4,2,2,2.

WITH scoped AS (
    SELECT cl.nit AS clinica, c.fecha_cita AS fecha, c.id_cita, c.id_paciente,
           upper(c.estado) AS estado, q.id_consulta
    FROM citas c JOIN clinicas cl ON cl.id_clinica = c.id_clinica
    LEFT JOIN consultas q ON q.id_cita = c.id_cita AND q.motivo_consulta LIKE 'CU22N26V1:%'
    WHERE cl.nit IN ('CU22N26V1-A','CU22N26V1-B') AND c.notas LIKE 'CU22N26V1:%'
)
SELECT clinica, fecha, count(DISTINCT id_cita) AS citas,
       count(DISTINCT id_cita) FILTER (WHERE estado = 'CANCELADA') AS cancelaciones,
       count(DISTINCT id_cita) FILTER (WHERE id_consulta IS NOT NULL) AS encuentros,
       count(DISTINCT id_paciente) FILTER (WHERE id_consulta IS NOT NULL) AS pacientes_unicos
FROM scoped GROUP BY clinica, fecha ORDER BY clinica, fecha;
-- A: 4 fechas, cada una 3/1/2/2. B: 2 fechas, cada una 2/1/1/1.

WITH scoped AS (
    SELECT cl.nit AS clinica, c.id_cita, c.id_paciente,
           CASE WHEN upper(trim(c.tipo_consulta)) IS NOT NULL
                     AND upper(trim(c.modalidad)) IS NOT NULL
                     AND upper(trim(c.tipo_consulta)) <> upper(trim(c.modalidad)) THEN 'CONFLICTO'
                WHEN coalesce(upper(trim(c.tipo_consulta)), upper(trim(c.modalidad)))
                     IN ('PRESENCIAL','TELEMEDICINA')
                     THEN coalesce(upper(trim(c.tipo_consulta)), upper(trim(c.modalidad)))
                ELSE 'OTRA' END AS modalidad,
           upper(c.estado) AS estado
    FROM citas c JOIN clinicas cl ON cl.id_clinica = c.id_clinica
    WHERE cl.nit IN ('CU22N26V1-A','CU22N26V1-B') AND c.notas LIKE 'CU22N26V1:%'
)
SELECT clinica, modalidad, count(*) AS citas,
       count(*) FILTER (WHERE estado='CANCELADA') AS cancelaciones
FROM scoped GROUP BY clinica, modalidad ORDER BY clinica, modalidad;
-- A PRESENCIAL 8/4 y TELEMEDICINA 4/0; B PRESENCIAL 2/1 y TELEMEDICINA 2/1.

SELECT cl.nit AS clinica, count(*) AS consultas,
       count(DISTINCT q.id_cita) AS citas_con_consulta
FROM consultas q JOIN clinicas cl ON cl.id_clinica = q.id_clinica
WHERE cl.nit IN ('CU22N26V1-A','CU22N26V1-B') AND q.motivo_consulta LIKE 'CU22N26V1:%'
GROUP BY cl.nit ORDER BY cl.nit;
-- A 8/8, B 2/2. El flujo HCE no admite una segunda consulta tras FINALIZADA.
