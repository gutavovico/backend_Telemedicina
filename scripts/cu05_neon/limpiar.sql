-- CU05NEONVERIFYV1. PREPARADO, NO EJECUTADO.
-- Ejecutar completo en SQL Editor solo después de las pruebas y de revisar las
-- ocho auditorías esperadas. Abortará si hay referencias ajenas al fixture.
BEGIN;
SET LOCAL statement_timeout = '20s';
SET LOCAL lock_timeout = '3s';

DO $cu05$
DECLARE
    marker constant text := 'CU05NEONVERIFYV1';
    clinic_ids bigint[];
    role_ids bigint[];
    user_ids bigint[];
    doctor_ids bigint[];
    patient_ids bigint[];
    appointment_ids bigint[];
    schedule_ids bigint[];
    block_ids bigint[];
    audit_ids bigint[];
    fk record;
    parent_ids bigint[];
    child_column text;
    references_count bigint;
    expected record;
BEGIN
    -- Impide que aparezcan nuevas relaciones mientras se verifica y elimina.
    LOCK TABLE clinicas, roles, usuarios, medicos, pacientes, citas,
               horarios_medicos, bloqueos_agenda, auditoria IN SHARE ROW EXCLUSIVE MODE;
    FOR fk IN SELECT DISTINCT conrelid FROM pg_constraint
              WHERE contype='f' AND confrelid IN
                ('clinicas'::regclass,'roles'::regclass,'usuarios'::regclass,
                 'medicos'::regclass,'pacientes'::regclass,'citas'::regclass,
                 'horarios_medicos'::regclass,'bloqueos_agenda'::regclass)
    LOOP
        EXECUTE format('LOCK TABLE %s IN SHARE ROW EXCLUSIVE MODE', fk.conrelid::regclass);
    END LOOP;

    SELECT array_agg(id_clinica ORDER BY id_clinica) INTO clinic_ids
    FROM clinicas WHERE nit IN (marker || '-A', marker || '-B');
    SELECT array_agg(id_rol ORDER BY id_rol) INTO role_ids FROM roles WHERE descripcion = marker;
    SELECT array_agg(id_usuario ORDER BY id_usuario) INTO user_ids FROM usuarios
    WHERE correo IN (
        'cu05neonverifyv1-admin-a@example.com', 'cu05neonverifyv1-medico-a@example.com',
        'cu05neonverifyv1-recepcion-a@example.com', 'cu05neonverifyv1-paciente-a@example.com',
        'cu05neonverifyv1-admin-b@example.com', 'cu05neonverifyv1-medico-b@example.com');
    SELECT array_agg(id_medico ORDER BY id_medico) INTO doctor_ids FROM medicos
    WHERE matricula_profesional IN (marker || '-A', marker || '-B');
    SELECT array_agg(id_paciente ORDER BY id_paciente) INTO patient_ids FROM pacientes
    WHERE ci IN (marker || '-A', marker || '-B');
    SELECT array_agg(id_cita ORDER BY id_cita) INTO appointment_ids FROM citas
    WHERE notas IN (marker || ':CANCELADA', marker || ':SIN_FIN');
    SELECT array_agg(id_horario ORDER BY id_horario) INTO schedule_ids FROM horarios_medicos
    WHERE id_medico = ANY(doctor_ids);
    SELECT array_agg(id_bloqueo ORDER BY id_bloqueo) INTO block_ids FROM bloqueos_agenda
    WHERE id_medico = ANY(doctor_ids);
    SELECT array_agg(id_auditoria ORDER BY id_auditoria) INTO audit_ids FROM auditoria
    WHERE id_clinica = ANY(clinic_ids);

    IF cardinality(clinic_ids) IS DISTINCT FROM 2 OR cardinality(role_ids) IS DISTINCT FROM 6
       OR cardinality(user_ids) IS DISTINCT FROM 6 OR cardinality(doctor_ids) IS DISTINCT FROM 2
       OR cardinality(patient_ids) IS DISTINCT FROM 2 OR cardinality(appointment_ids) IS DISTINCT FROM 2
       OR cardinality(schedule_ids) IS DISTINCT FROM 2 OR cardinality(block_ids) IS DISTINCT FROM 2
       OR cardinality(audit_ids) IS DISTINCT FROM 8 THEN
        RAISE EXCEPTION 'CU05NEONVERIFYV1: conteos inesperados; no se borró nada';
    END IF;
    IF EXISTS (SELECT 1 FROM clinicas WHERE nit LIKE marker || '%' AND id_clinica <> ALL(clinic_ids))
       OR EXISTS (SELECT 1 FROM usuarios WHERE correo LIKE 'cu05neonverifyv1-%@example.com'
                  AND id_usuario <> ALL(user_ids))
       OR EXISTS (SELECT 1 FROM medicos WHERE matricula_profesional LIKE marker || '%'
                  AND id_medico <> ALL(doctor_ids))
       OR EXISTS (SELECT 1 FROM pacientes WHERE ci LIKE marker || '%'
                  AND id_paciente <> ALL(patient_ids))
       OR EXISTS (SELECT 1 FROM citas WHERE notas LIKE marker || '%'
                  AND id_cita <> ALL(appointment_ids))
       OR EXISTS (SELECT 1 FROM bloqueos_agenda WHERE motivo LIKE marker || '%'
                  AND id_bloqueo <> ALL(block_ids)) THEN
        RAISE EXCEPTION 'CU05NEONVERIFYV1: marcador ampliado o colisión; no se borró nada';
    END IF;

    FOR expected IN SELECT * FROM (VALUES
        ('cu05neonverifyv1-admin-a@example.com', 'A', 'ADMIN'),
        ('cu05neonverifyv1-medico-a@example.com', 'A', 'MEDICO'),
        ('cu05neonverifyv1-recepcion-a@example.com', 'A', 'RECEPCION'),
        ('cu05neonverifyv1-paciente-a@example.com', 'A', 'PACIENTE'),
        ('cu05neonverifyv1-admin-b@example.com', 'B', 'ADMIN'),
        ('cu05neonverifyv1-medico-b@example.com', 'B', 'MEDICO')) v(email, code, role)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM usuarios u JOIN roles r ON r.id_rol=u.id_rol
            JOIN clinicas c ON c.id_clinica=u.id_clinica
            WHERE u.correo=expected.email AND c.nit=marker || '-' || expected.code
              AND r.nombre=expected.role AND r.descripcion=marker
              AND r.id_clinica=u.id_clinica) THEN
            RAISE EXCEPTION 'CU05NEONVERIFYV1: relación cuenta/rol/clínica alterada';
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM medicos m JOIN usuarios u ON u.id_usuario=m.id_usuario
               WHERE m.id_medico=ANY(doctor_ids) AND m.id_clinica IS DISTINCT FROM u.id_clinica)
       OR (SELECT count(*) FROM medicos WHERE id_usuario=ANY(user_ids)) <> 2
       OR (SELECT count(*) FROM pacientes WHERE id_usuario=ANY(user_ids)) <> 1
       OR (SELECT count(*) FROM citas WHERE id_clinica=ANY(clinic_ids)) <> 2
       OR (SELECT count(*) FROM citas WHERE id_medico=ANY(doctor_ids)) <> 2
       OR (SELECT count(*) FROM citas WHERE id_paciente=ANY(patient_ids)) <> 2
       OR (SELECT count(*) FROM horarios_medicos WHERE id_medico=ANY(doctor_ids)) <> 2
       OR (SELECT count(*) FROM bloqueos_agenda WHERE id_medico=ANY(doctor_ids)) <> 2
       OR (SELECT count(*) FROM roles WHERE id_clinica=ANY(clinic_ids)) <> 6
       OR (SELECT count(*) FROM usuarios WHERE id_clinica=ANY(clinic_ids)) <> 6
       OR (SELECT count(*) FROM usuarios WHERE id_rol=ANY(role_ids)) <> 6
       OR (SELECT count(*) FROM medicos WHERE id_clinica=ANY(clinic_ids)) <> 2
       OR (SELECT count(*) FROM pacientes WHERE id_clinica=ANY(clinic_ids)) <> 2
       OR (SELECT count(*) FROM auditoria WHERE id_usuario=ANY(user_ids)) <> 8
       OR (SELECT count(*) FROM notificaciones WHERE id_usuario=ANY(user_ids)) <> 0 THEN
        RAISE EXCEPTION 'CU05NEONVERIFYV1: referencias inesperadas; no se borró nada';
    END IF;
    IF EXISTS (SELECT 1 FROM citas WHERE id_cita=ANY(appointment_ids) AND
               (id_clinica <> (SELECT id_clinica FROM clinicas WHERE nit=marker || '-A')
                OR notas NOT IN (marker || ':CANCELADA', marker || ':SIN_FIN')))
       OR EXISTS (SELECT 1 FROM horarios_medicos WHERE id_horario=ANY(schedule_ids)
                  AND (id_servicio <> 1 OR estado <> 'activo'))
       OR EXISTS (SELECT 1 FROM bloqueos_agenda WHERE id_bloqueo=ANY(block_ids)
                  AND (id_servicio <> 1 OR estado <> 'LIBERADO'
                       OR motivo NOT IN (marker || ':FLUJO', marker || ':CANCELADA')))
       OR EXISTS (SELECT 1 FROM auditoria WHERE id_auditoria=ANY(audit_ids)
                  AND NOT (id_usuario=ANY(user_ids) AND (
                      (tabla_afectada='horarios_medicos' AND registro_id=ANY(schedule_ids)
                       AND accion='CREAR') OR
                      (tabla_afectada='bloqueos_agenda' AND registro_id=ANY(block_ids)
                       AND accion IN ('SOLICITAR','APROBAR','LIBERAR'))))) THEN
        RAISE EXCEPTION 'CU05NEONVERIFYV1: estado de prueba alterado; no se borró nada';
    END IF;

    -- Protege incluso tablas nuevas con FK de una columna hacia el fixture.
    FOR fk IN
        SELECT con.conrelid, con.confrelid, con.conkey, con.confkey
        FROM pg_constraint con WHERE con.contype='f' AND con.confrelid IN
            ('clinicas'::regclass,'roles'::regclass,'usuarios'::regclass,
             'medicos'::regclass,'pacientes'::regclass,'citas'::regclass,
             'horarios_medicos'::regclass,'bloqueos_agenda'::regclass)
    LOOP
        IF array_length(fk.conkey, 1) <> 1 OR array_length(fk.confkey, 1) <> 1 THEN
            RAISE EXCEPTION 'CU05NEONVERIFYV1: FK compuesta no revisada; no se borró nada';
        END IF;
        CASE fk.confrelid
            WHEN 'clinicas'::regclass THEN parent_ids := clinic_ids;
            WHEN 'roles'::regclass THEN parent_ids := role_ids;
            WHEN 'usuarios'::regclass THEN parent_ids := user_ids;
            WHEN 'medicos'::regclass THEN parent_ids := doctor_ids;
            WHEN 'pacientes'::regclass THEN parent_ids := patient_ids;
            WHEN 'citas'::regclass THEN parent_ids := appointment_ids;
            WHEN 'horarios_medicos'::regclass THEN parent_ids := schedule_ids;
            WHEN 'bloqueos_agenda'::regclass THEN parent_ids := block_ids;
        END CASE;
        IF fk.conrelid IN ('roles'::regclass,'usuarios'::regclass,'medicos'::regclass,
                           'pacientes'::regclass,'citas'::regclass,'horarios_medicos'::regclass,
                           'bloqueos_agenda'::regclass,'auditoria'::regclass) THEN
            CONTINUE;  -- Estas referencias se verificaron arriba por conteos y marcador.
        END IF;
        SELECT attname INTO child_column FROM pg_attribute
        WHERE attrelid=fk.conrelid AND attnum=fk.conkey[1];
        EXECUTE format('SELECT count(*) FROM %s WHERE %I = ANY($1)',
                       fk.conrelid::regclass, child_column)
        INTO references_count USING parent_ids;
        IF references_count <> 0 THEN
            RAISE EXCEPTION 'CU05NEONVERIFYV1: referencia externa en %; no se borró nada',
                            fk.conrelid::regclass;
        END IF;
    END LOOP;

    DELETE FROM auditoria WHERE id_auditoria=ANY(audit_ids);
    DELETE FROM bloqueos_agenda WHERE id_bloqueo=ANY(block_ids);
    DELETE FROM horarios_medicos WHERE id_horario=ANY(schedule_ids);
    DELETE FROM citas WHERE id_cita=ANY(appointment_ids);
    DELETE FROM pacientes WHERE id_paciente=ANY(patient_ids);
    DELETE FROM medicos WHERE id_medico=ANY(doctor_ids);
    DELETE FROM usuarios WHERE id_usuario=ANY(user_ids);
    DELETE FROM roles WHERE id_rol=ANY(role_ids);
    DELETE FROM clinicas WHERE id_clinica=ANY(clinic_ids);
END
$cu05$;
COMMIT;
