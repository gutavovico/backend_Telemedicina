-- CU22N26V1: ejecutar manualmente UNA vez en SQL Editor, solo tras revisar verificar.sql.
-- Cambia exclusivamente los ocho correos originales del fixture. No modifica
-- IDs, hashes, roles, clinicas ni datos clinicos. No ejecutado por Codex.
BEGIN;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '3s';

-- Bloquea escrituras concurrentes mientras se comprueban y actualizan las cuentas.
-- SELECT/login sigue permitido. Si no se puede obtener el bloqueo, aborta.
LOCK TABLE clinicas, roles, usuarios IN SHARE ROW EXCLUSIVE MODE NOWAIT;

DO $cu22_email$
DECLARE
    marker constant text := 'CU22N26V1';
    old_emails constant text[] := ARRAY[
        'cu22n26v1-admin-a@example.invalid',
        'cu22n26v1-medico-a@example.invalid',
        'cu22n26v1-recepcion-a@example.invalid',
        'cu22n26v1-paciente-a@example.invalid',
        'cu22n26v1-admin-b@example.invalid',
        'cu22n26v1-medico-b@example.invalid',
        'cu22n26v1-recepcion-b@example.invalid',
        'cu22n26v1-paciente-b@example.invalid'
    ];
    clinic_nits constant text[] := ARRAY[
        'CU22N26V1-A', 'CU22N26V1-A', 'CU22N26V1-A', 'CU22N26V1-A',
        'CU22N26V1-B', 'CU22N26V1-B', 'CU22N26V1-B', 'CU22N26V1-B'
    ];
    role_names constant text[] := ARRAY[
        'ADMIN', 'MEDICO', 'RECEPCION', 'PACIENTE',
        'ADMIN', 'MEDICO', 'RECEPCION', 'PACIENTE'
    ];
    new_email text;
    matched bigint;
    changed integer;
    i integer;
BEGIN
    IF (SELECT count(*) FROM clinicas WHERE nit IN (marker || '-A', marker || '-B')) <> 2
       OR (SELECT count(*) FROM roles WHERE descripcion = marker) <> 8
       OR (SELECT count(*) FROM usuarios u JOIN clinicas c ON c.id_clinica = u.id_clinica
           WHERE c.nit IN (marker || '-A', marker || '-B')) <> 8
       OR (SELECT count(*) FROM citas WHERE notas LIKE marker || ':%') <> 16
       OR (SELECT count(*) FROM consultas WHERE motivo_consulta LIKE marker || ':%') <> 10 THEN
        RAISE EXCEPTION 'CU22N26V1: fixture en estado inesperado';
    END IF;

    -- Primera pasada: las ocho relaciones deben ser exactas y los destinos libres.
    FOR i IN 1..8 LOOP
        new_email := replace(old_emails[i], '@example.invalid', '@example.com');
        SELECT count(*) INTO matched
        FROM usuarios u
        JOIN clinicas c ON c.id_clinica = u.id_clinica
        JOIN roles r ON r.id_rol = u.id_rol
        WHERE u.correo = old_emails[i]
          AND c.nit = clinic_nits[i]
          AND r.nombre = role_names[i]
          AND r.descripcion = marker
          AND r.id_clinica = u.id_clinica
          AND lower(u.estado) = 'activo'
          AND lower(r.estado) = 'activo'
          AND lower(c.estado) = 'activo';
        IF matched <> 1
           OR (SELECT count(*) FROM usuarios WHERE lower(correo) = old_emails[i]) <> 1
           OR EXISTS (SELECT 1 FROM usuarios WHERE lower(correo) = new_email) THEN
            RAISE EXCEPTION 'CU22N26V1: cuenta %, relacion o destino inesperado', i;
        END IF;
    END LOOP;

    -- Segunda pasada: WHERE usa cada correo completo, nunca un patron amplio.
    FOR i IN 1..8 LOOP
        new_email := replace(old_emails[i], '@example.invalid', '@example.com');
        UPDATE usuarios SET correo = new_email WHERE correo = old_emails[i];
        GET DIAGNOSTICS changed = ROW_COUNT;
        IF changed <> 1 THEN
            RAISE EXCEPTION 'CU22N26V1: actualizacion incompleta en cuenta %', i;
        END IF;
    END LOOP;
END
$cu22_email$;
COMMIT;
