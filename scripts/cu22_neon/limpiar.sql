-- CU22N26V1: limpiar SOLO el conjunto sintético tras revisar verificar.sql.
-- REVISION ESTATICA; NO EJECUTADO. Si algo falta o tiene referencias ajenas,
-- RAISE EXCEPTION revierte la transacción. Nunca usa fechas como criterio DELETE.
BEGIN;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '3s';

DO $cu22$
DECLARE
    marker constant text := 'CU22N26V1';
    clinic_ids bigint[];
    role_ids bigint[];
    user_ids bigint[];
    doctor_ids bigint[];
    patient_ids bigint[];
    specialty_ids bigint[];
    appointment_ids bigint[];
    history_ids bigint[];
    consultation_ids bigint[];
    parent_ids bigint[];
    allowed_child_ids bigint[];
    parent_name text;
    child_name text;
    child_pk text;
    outside_count bigint;
    fk record;
BEGIN
    SELECT ARRAY(SELECT id_clinica FROM clinicas WHERE nit IN (marker || '-A', marker || '-B')) INTO clinic_ids;
    SELECT ARRAY(SELECT id_rol FROM roles WHERE descripcion = marker AND id_clinica = ANY(clinic_ids)) INTO role_ids;
    -- Reconoce exactamente las ocho combinaciones rol/clinica con dominio
    -- original o corregido. No selecciona otras cuentas por prefijo.
    SELECT ARRAY(SELECT id_usuario FROM usuarios WHERE correo ~
                 '^cu22n26v1-(admin|medico|recepcion|paciente)-(a|b)@example[.](invalid|com)$') INTO user_ids;
    SELECT ARRAY(SELECT id_medico FROM medicos WHERE matricula_profesional IN (marker || '-M-A', marker || '-M-B')) INTO doctor_ids;
    SELECT ARRAY(SELECT id_paciente FROM pacientes WHERE ci LIKE marker || '%') INTO patient_ids;
    SELECT ARRAY(SELECT id_especialidad FROM especialidades WHERE nombre IN
                 (marker || '-Especialidad-A', marker || '-Especialidad-B')) INTO specialty_ids;
    SELECT ARRAY(SELECT id_cita FROM citas WHERE notas LIKE marker || ':%') INTO appointment_ids;
    SELECT ARRAY(SELECT id_historia FROM historias_clinicas WHERE numero_historia LIKE marker || '-H-%') INTO history_ids;
    SELECT ARRAY(SELECT id_consulta FROM consultas WHERE motivo_consulta LIKE marker || ':%') INTO consultation_ids;

    IF cardinality(clinic_ids) <> 2 OR cardinality(role_ids) <> 8
       OR cardinality(user_ids) <> 8 OR cardinality(doctor_ids) <> 2
       OR cardinality(patient_ids) <> 4 OR cardinality(specialty_ids) <> 2
       OR cardinality(appointment_ids) <> 16 OR cardinality(history_ids) <> 4
       OR cardinality(consultation_ids) <> 10
       OR (SELECT count(DISTINCT (id_clinica, id_rol)) FROM usuarios
           WHERE id_usuario = ANY(user_ids)) <> 8 THEN
        RAISE EXCEPTION 'CU22N26V1 incompleto o alterado: no se borró nada';
    END IF;
    IF (SELECT count(*) FROM medico_especialidad
        WHERE id_medico = ANY(doctor_ids) OR id_especialidad = ANY(specialty_ids)) <> 2
       OR EXISTS (SELECT 1 FROM medico_especialidad
                  WHERE (id_medico = ANY(doctor_ids) OR id_especialidad = ANY(specialty_ids))
                    AND NOT (id_medico = ANY(doctor_ids) AND id_especialidad = ANY(specialty_ids)))
       OR EXISTS (SELECT 1 FROM roles WHERE id_rol = ANY(role_ids)
                    AND NOT (id_clinica = ANY(clinic_ids) AND nombre IN ('ADMIN','MEDICO','RECEPCION','PACIENTE')))
       OR EXISTS (SELECT 1 FROM usuarios u
                  LEFT JOIN roles r ON r.id_rol = u.id_rol
                  LEFT JOIN clinicas c ON c.id_clinica = u.id_clinica
                  WHERE u.id_usuario = ANY(user_ids)
                    AND (u.id_clinica = ANY(clinic_ids) AND u.id_rol = ANY(role_ids)
                             AND r.id_clinica = u.id_clinica AND r.descripcion = marker
                             AND c.nit IN (marker || '-A', marker || '-B')
                             AND u.correo IN (
                                 lower(marker || '-' || r.nombre || '-' || right(c.nit, 1) || '@example.invalid'),
                                 lower(marker || '-' || r.nombre || '-' || right(c.nit, 1) || '@example.com'))) IS NOT TRUE)
       OR EXISTS (SELECT 1 FROM medicos WHERE id_medico = ANY(doctor_ids)
                    AND NOT (id_clinica = ANY(clinic_ids) AND id_usuario = ANY(user_ids)))
       OR EXISTS (SELECT 1 FROM pacientes WHERE id_paciente = ANY(patient_ids)
                    AND NOT (id_clinica = ANY(clinic_ids) AND (id_usuario IS NULL OR id_usuario = ANY(user_ids))))
       OR EXISTS (SELECT 1 FROM historias_clinicas WHERE id_historia = ANY(history_ids)
                    AND NOT (id_clinica = ANY(clinic_ids) AND id_paciente = ANY(patient_ids)))
       OR EXISTS (SELECT 1 FROM citas WHERE id_cita = ANY(appointment_ids)
                    AND NOT (id_clinica = ANY(clinic_ids) AND id_paciente = ANY(patient_ids)
                             AND id_medico = ANY(doctor_ids) AND id_especialidad = ANY(specialty_ids)
                             AND fecha_cita BETWEEN DATE '2026-07-01' AND DATE '2026-07-31'))
       OR EXISTS (SELECT 1 FROM consultas WHERE id_consulta = ANY(consultation_ids)
                    AND NOT (id_clinica = ANY(clinic_ids) AND id_historia = ANY(history_ids)
                             AND id_cita = ANY(appointment_ids) AND id_medico = ANY(doctor_ids))) THEN
        RAISE EXCEPTION 'CU22N26V1 tiene relaciones alteradas: no se borró nada';
    END IF;

    -- usuarios.id_clinica/id_rol do not have physical FKs in the observed DB.
    IF EXISTS (SELECT 1 FROM usuarios WHERE id_usuario <> ALL(user_ids)
                 AND (id_clinica = ANY(clinic_ids) OR id_rol = ANY(role_ids))) THEN
        RAISE EXCEPTION 'Usuarios ajenos apuntan a clínicas/roles de CU22N26V1';
    END IF;

    -- Inspect EVERY current single-column FK pointing to an owned parent.
    -- A new or unknown child table with a reference aborts instead of cascading.
    FOR fk IN
        SELECT c.conrelid, c.confrelid, c.conkey, c.confkey,
               a.attname AS child_column,
               parent.relname AS parent_table, child.relname AS child_table
        FROM pg_constraint c
        JOIN pg_class parent ON parent.oid = c.confrelid
        JOIN pg_class child ON child.oid = c.conrelid
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND c.confrelid = ANY(ARRAY[
            'public.clinicas'::regclass, 'public.roles'::regclass,
            'public.usuarios'::regclass, 'public.medicos'::regclass,
            'public.pacientes'::regclass, 'public.especialidades'::regclass,
            'public.citas'::regclass, 'public.historias_clinicas'::regclass,
            'public.consultas'::regclass
        ])
    LOOP
        IF cardinality(fk.conkey) <> 1 OR cardinality(fk.confkey) <> 1 THEN
            RAISE EXCEPTION 'FK compuesta nueva hacia CU22N26V1: revisar limpieza';
        END IF;
        parent_name := fk.parent_table;
        child_name := fk.child_table;
        parent_ids := CASE parent_name
            WHEN 'clinicas' THEN clinic_ids WHEN 'roles' THEN role_ids
            WHEN 'usuarios' THEN user_ids WHEN 'medicos' THEN doctor_ids
            WHEN 'pacientes' THEN patient_ids WHEN 'especialidades' THEN specialty_ids
            WHEN 'citas' THEN appointment_ids WHEN 'historias_clinicas' THEN history_ids
            WHEN 'consultas' THEN consultation_ids END;
        allowed_child_ids := CASE child_name
            WHEN 'clinicas' THEN clinic_ids WHEN 'roles' THEN role_ids
            WHEN 'usuarios' THEN user_ids WHEN 'medicos' THEN doctor_ids
            WHEN 'pacientes' THEN patient_ids WHEN 'especialidades' THEN specialty_ids
            WHEN 'citas' THEN appointment_ids WHEN 'historias_clinicas' THEN history_ids
            WHEN 'consultas' THEN consultation_ids ELSE NULL END;
        child_pk := CASE child_name
            WHEN 'clinicas' THEN 'id_clinica' WHEN 'roles' THEN 'id_rol'
            WHEN 'usuarios' THEN 'id_usuario' WHEN 'medicos' THEN 'id_medico'
            WHEN 'pacientes' THEN 'id_paciente' WHEN 'especialidades' THEN 'id_especialidad'
            WHEN 'citas' THEN 'id_cita' WHEN 'historias_clinicas' THEN 'id_historia'
            WHEN 'consultas' THEN 'id_consulta' ELSE NULL END;
        IF child_name = 'medico_especialidad' THEN
            EXECUTE format('SELECT count(*) FROM %s WHERE %I = ANY($1) AND NOT (id_medico = ANY($2) AND id_especialidad = ANY($3))',
                           fk.conrelid::regclass, fk.child_column)
            INTO outside_count USING parent_ids, doctor_ids, specialty_ids;
        ELSIF child_pk IS NOT NULL THEN
            EXECUTE format('SELECT count(*) FROM %s WHERE %I = ANY($1) AND NOT (%I = ANY($2))',
                           fk.conrelid::regclass, fk.child_column, child_pk)
            INTO outside_count USING parent_ids, allowed_child_ids;
        ELSE
            EXECUTE format('SELECT count(*) FROM %s WHERE %I = ANY($1)',
                           fk.conrelid::regclass, fk.child_column)
            INTO outside_count USING parent_ids;
        END IF;
        IF outside_count > 0 THEN
            RAISE EXCEPTION 'Referencia ajena desde % hacia %: no se borró nada', child_name, parent_name;
        END IF;
    END LOOP;

    DELETE FROM consultas WHERE id_consulta = ANY(consultation_ids);
    DELETE FROM citas WHERE id_cita = ANY(appointment_ids);
    DELETE FROM medico_especialidad WHERE id_medico = ANY(doctor_ids)
                                      AND id_especialidad = ANY(specialty_ids);
    DELETE FROM historias_clinicas WHERE id_historia = ANY(history_ids);
    DELETE FROM pacientes WHERE id_paciente = ANY(patient_ids);
    DELETE FROM medicos WHERE id_medico = ANY(doctor_ids);
    DELETE FROM usuarios WHERE id_usuario = ANY(user_ids);
    DELETE FROM roles WHERE id_rol = ANY(role_ids);
    DELETE FROM especialidades WHERE id_especialidad = ANY(specialty_ids);
    DELETE FROM clinicas WHERE id_clinica = ANY(clinic_ids);
END
$cu22$;
COMMIT;
