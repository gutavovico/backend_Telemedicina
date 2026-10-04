-- CU22N26V1: ejecutar una sola vez, completo, en SQL Editor de la rama Neon revisada.
-- El conjunto CU22N26V1 ya existe en Neon: NO volver a ejecutar alli.
-- Se conserva para futuras poblaciones aisladas con el dominio valido example.com.
-- Usa solo IDs generados. No usa registros del equipo.
-- La contraseña sintética común y su hash bcrypt generado por app.core.security
-- se describen en README.md. No usar estas cuentas fuera de esta prueba.
BEGIN;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '3s';

DO $cu22$
DECLARE
    marker constant text := 'CU22N26V1';
    password_bcrypt constant text := '$2b$12$TntHrne38tkop0C8yGvUeOxkj6YICFY0bOn4C5oWMOMFHsaJqAC72';
    clinics bigint[] := ARRAY[NULL::bigint, NULL::bigint];
    doctors bigint[] := ARRAY[NULL::bigint, NULL::bigint];
    specialties bigint[] := ARRAY[NULL::bigint, NULL::bigint];
    users bigint[] := array_fill(NULL::bigint, ARRAY[8]);
    patients bigint[] := array_fill(NULL::bigint, ARRAY[4]);
    histories bigint[] := array_fill(NULL::bigint, ARRAY[4]);
    generated_id bigint;
    role_id bigint;
    appointment_id bigint;
    clinic_code text;
    role_code text;
    day_of_month date;
    patient_id bigint;
    appointment_state text;
    mode text;
    start_hour text;
    end_hour text;
    i integer;
    j integer;
BEGIN
    -- Abort on duplicate marker OR on team activity in the reserved period.
    IF EXISTS (SELECT 1 FROM clinicas WHERE nit IN ('CU22N26V1-A', 'CU22N26V1-B'))
       OR EXISTS (SELECT 1 FROM roles WHERE descripcion = marker)
       OR EXISTS (SELECT 1 FROM usuarios WHERE correo ~
           '^cu22n26v1-(admin|medico|recepcion|paciente)-(a|b)@example[.](invalid|com)$')
       OR EXISTS (SELECT 1 FROM medicos WHERE matricula_profesional LIKE 'CU22N26V1-%')
       OR EXISTS (SELECT 1 FROM pacientes WHERE ci LIKE 'CU22N26V1%')
       OR EXISTS (SELECT 1 FROM especialidades WHERE nombre LIKE 'CU22N26V1-%')
       OR EXISTS (SELECT 1 FROM historias_clinicas WHERE numero_historia LIKE 'CU22N26V1-%')
       OR EXISTS (SELECT 1 FROM citas WHERE notas LIKE 'CU22N26V1:%')
       OR EXISTS (SELECT 1 FROM consultas WHERE motivo_consulta LIKE 'CU22N26V1:%') THEN
        RAISE EXCEPTION 'CU22N26V1 ya existe o el marcador colisiona; no se insertó nada';
    END IF;
    IF EXISTS (SELECT 1 FROM citas WHERE fecha_cita BETWEEN DATE '2026-07-01' AND DATE '2026-07-31')
       OR EXISTS (SELECT 1 FROM consultas WHERE fecha_consulta >= TIMESTAMP '2026-07-01'
                                               AND fecha_consulta < TIMESTAMP '2026-08-01') THEN
        RAISE EXCEPTION 'Julio 2026 contiene datos ajenos; elegir otro período y recalcular expectativas';
    END IF;

    FOR i IN 1..2 LOOP
        clinic_code := CASE i WHEN 1 THEN 'A' ELSE 'B' END;
        INSERT INTO clinicas (nombre, razon_social, nit, estado)
        VALUES (marker || ' Clínica ' || clinic_code, 'Prueba sintética CU22', marker || '-' || clinic_code, 'ACTIVO')
        RETURNING id_clinica INTO generated_id;
        clinics[i] := generated_id;

        FOR j IN 1..4 LOOP
            role_code := (ARRAY['ADMIN', 'MEDICO', 'RECEPCION', 'PACIENTE'])[j];
            INSERT INTO roles (id_clinica, nombre, descripcion, estado)
            VALUES (clinics[i], role_code, marker, 'ACTIVO') RETURNING id_rol INTO role_id;
            INSERT INTO usuarios (id_clinica, id_rol, nombres, apellidos, correo, password_hash, estado)
            VALUES (
                clinics[i], role_id, 'Sintético', clinic_code || ' ' || role_code,
                lower(marker || '-' || lower(role_code) || '-' || clinic_code || '@example.com'),
                password_bcrypt, 'activo'
            ) RETURNING id_usuario INTO generated_id;
            users[(i - 1) * 4 + j] := generated_id;
        END LOOP;

        INSERT INTO especialidades (nombre, descripcion, estado)
        VALUES (marker || '-Especialidad-' || clinic_code, 'Prueba sintética CU22', 'activo')
        RETURNING id_especialidad INTO generated_id;
        specialties[i] := generated_id;
        INSERT INTO medicos (id_usuario, id_clinica, matricula_profesional, estado)
        VALUES (users[(i - 1) * 4 + 2], clinics[i], marker || '-M-' || clinic_code, 'activo')
        RETURNING id_medico INTO generated_id;
        doctors[i] := generated_id;
        INSERT INTO medico_especialidad (id_medico, id_especialidad, es_principal)
        VALUES (doctors[i], specialties[i], true);

        FOR j IN 1..2 LOOP
            INSERT INTO pacientes (
                id_clinica, id_usuario, nombres, apellidos, ci, complemento,
                fecha_nacimiento, genero, telefono, estado
            ) VALUES (
                clinics[i], CASE WHEN j = 1 THEN users[(i - 1) * 4 + 4] ELSE NULL END,
                'Paciente sintético', clinic_code || j::text,
                marker || clinic_code || j::text, '', DATE '1990-01-01',
                CASE WHEN j = 1 THEN 'F' ELSE 'M' END, '000000000', 'ACTIVO'
            ) RETURNING id_paciente INTO generated_id;
            patients[(i - 1) * 2 + j] := generated_id;
            INSERT INTO historias_clinicas (id_clinica, id_paciente, numero_historia)
            VALUES (clinics[i], patients[(i - 1) * 2 + j], marker || '-H-' || clinic_code || j::text)
            RETURNING id_historia INTO generated_id;
            histories[(i - 1) * 2 + j] := generated_id;
        END LOOP;
    END LOOP;

    -- Clínica A: cuatro fechas, tres citas por fecha. Dos encuentros y una
    -- cancelación; los mismos dos pacientes aparecen en las cuatro fechas.
    FOR i IN 1..4 LOOP
        day_of_month := (ARRAY[DATE '2026-07-02', DATE '2026-07-07',
                               DATE '2026-07-14', DATE '2026-07-21'])[i];
        FOR j IN 1..3 LOOP
            patient_id := CASE WHEN j = 2 THEN patients[2] ELSE patients[1] END;
            appointment_state := CASE WHEN j = 3 THEN 'CANCELADA' ELSE 'FINALIZADA' END;
            mode := CASE WHEN j = 2 THEN 'TELEMEDICINA' ELSE 'PRESENCIAL' END;
            start_hour := (ARRAY['09:00', '09:30', '10:00'])[j];
            end_hour := (ARRAY['09:30', '10:00', '10:30'])[j];
            INSERT INTO citas (
                id_clinica, id_paciente, id_medico, id_especialidad, fecha_cita,
                hora_inicio, hora_fin, estado, tipo_consulta, modalidad, motivo, notas
            ) VALUES (
                clinics[1], patient_id, doctors[1], specialties[1], day_of_month,
                start_hour, end_hour, appointment_state, mode, mode,
                'Prueba sintética de reportes', marker || ':A:' || i::text || ':' || j::text
            ) RETURNING id_cita INTO appointment_id;
            IF j < 3 THEN
                INSERT INTO consultas (
                    id_clinica, id_historia, id_cita, id_medico,
                    motivo_consulta, sintomas, evolucion, plan_medico, fecha_consulta
                ) VALUES (
                    clinics[1], histories[j], appointment_id, doctors[1],
                    marker || ':A:' || i::text || ':' || j::text,
                    'Texto sintético', 'Evolución sintética', 'Plan sintético',
                    day_of_month + TIME '12:00'
                );
            END IF;
        END LOOP;
    END LOOP;

    -- Clínica B: dos fechas. Una cita con consulta y una cancelada por fecha.
    FOR i IN 1..2 LOOP
        day_of_month := (ARRAY[DATE '2026-07-03', DATE '2026-07-17'])[i];
        FOR j IN 1..2 LOOP
            patient_id := patients[2 + j];
            appointment_state := CASE WHEN i = j THEN 'FINALIZADA' ELSE 'CANCELADA' END;
            mode := CASE WHEN j = 1 THEN 'PRESENCIAL' ELSE 'TELEMEDICINA' END;
            start_hour := (ARRAY['11:00', '11:30'])[j];
            end_hour := (ARRAY['11:30', '12:00'])[j];
            INSERT INTO citas (
                id_clinica, id_paciente, id_medico, id_especialidad, fecha_cita,
                hora_inicio, hora_fin, estado, tipo_consulta, modalidad, motivo, notas
            ) VALUES (
                clinics[2], patient_id, doctors[2], specialties[2], day_of_month,
                start_hour, end_hour, appointment_state, mode, mode,
                'Prueba sintética de reportes', marker || ':B:' || i::text || ':' || j::text
            ) RETURNING id_cita INTO appointment_id;
            IF appointment_state = 'FINALIZADA' THEN
                INSERT INTO consultas (
                    id_clinica, id_historia, id_cita, id_medico,
                    motivo_consulta, sintomas, evolucion, plan_medico, fecha_consulta
                ) VALUES (
                    clinics[2], histories[2 + j], appointment_id, doctors[2],
                    marker || ':B:' || i::text || ':' || j::text,
                    'Texto sintético', 'Evolución sintética', 'Plan sintético',
                    day_of_month + TIME '12:30'
                );
            END IF;
        END LOOP;
    END LOOP;

    IF (SELECT count(*) FROM citas WHERE notas LIKE marker || ':%') <> 16
       OR (SELECT count(*) FROM consultas WHERE motivo_consulta LIKE marker || ':%') <> 10 THEN
        RAISE EXCEPTION 'Cantidad sintética inesperada; se revierte toda la transacción';
    END IF;
END
$cu22$;
COMMIT;
