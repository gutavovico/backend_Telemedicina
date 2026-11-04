-- CU17 para Neon/PostgreSQL. Generado con:
-- python -m alembic upgrade backup01ab23cd:cu17_backup_merge_015 --sql
-- Ejecutar SOLO si alembic_version contiene backup01ab23cd y no existe ninguna
-- de las nueve tablas CU17. Si la base ya esta en cu17_backup_merge_015,
-- NO ejecutar este archivo: el esquema ya esta instalado.
-- El script es transaccional y no contiene datos clinicos ni credenciales.
-- Tomar un respaldo antes de ejecutarlo. No usar CREATE TABLE IF NOT EXISTS
-- para ocultar una instalacion parcial; revisar ese caso antes de continuar.

BEGIN;

DO $cu17_guard$
DECLARE
    revisions text[];
BEGIN
    IF to_regclass('alembic_version') IS NULL THEN
        RAISE EXCEPTION 'Falta alembic_version: aplicar primero las migraciones base';
    END IF;
    SELECT array_agg(version_num ORDER BY version_num) INTO revisions FROM alembic_version;
    IF revisions IS DISTINCT FROM ARRAY['backup01ab23cd']::text[] THEN
        RAISE EXCEPTION 'Revision Alembic inesperada: se requiere backup01ab23cd';
    END IF;
    IF to_regclass('tratamientos') IS NOT NULL
       OR to_regclass('tratamiento_medicamentos') IS NOT NULL
       OR to_regclass('tratamiento_dosis') IS NOT NULL
       OR to_regclass('tratamiento_eventos') IS NOT NULL
       OR to_regclass('tratamiento_operaciones_dosis') IS NOT NULL
       OR to_regclass('tratamiento_avisos') IS NOT NULL
       OR to_regclass('tratamiento_dispositivos') IS NOT NULL
       OR to_regclass('tratamiento_entregas_push') IS NOT NULL
       OR to_regclass('tratamiento_cursores') IS NOT NULL THEN
        RAISE EXCEPTION 'Se detectaron tablas CU17: revisar el estado existente antes de migrar';
    END IF;
END
$cu17_guard$;


-- Running upgrade f7a8b9c0d1e2 -> cu17_tratamientos_013

CREATE TABLE tratamientos (
    id_tratamiento BIGSERIAL NOT NULL,
    id_clinica BIGINT NOT NULL,
    id_consulta BIGINT NOT NULL,
    id_receta BIGINT,
    id_diagnostico BIGINT NOT NULL,
    id_paciente BIGINT NOT NULL,
    id_medico BIGINT NOT NULL,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    zona_horaria VARCHAR(100) NOT NULL,
    estado VARCHAR(30) DEFAULT 'ACTIVO' NOT NULL,
    notas TEXT,
    motivo_cierre TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id_tratamiento),
    CONSTRAINT uq_tratamiento_clinica_receta UNIQUE (id_clinica, id_receta),
    CONSTRAINT ck_tratamiento_fechas CHECK (fecha_fin >= fecha_inicio),
    CONSTRAINT ck_tratamiento_estado CHECK (estado IN ('ACTIVO','FINALIZADO','SUSPENDIDO_POR_RECETA')),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_consulta) REFERENCES consultas (id_consulta),
    FOREIGN KEY(id_receta) REFERENCES recetas (id_receta),
    FOREIGN KEY(id_diagnostico) REFERENCES diagnosticos (id_diagnostico),
    FOREIGN KEY(id_paciente) REFERENCES pacientes (id_paciente),
    FOREIGN KEY(id_medico) REFERENCES medicos (id_medico)
);

CREATE INDEX ix_tratamiento_paciente ON tratamientos (id_clinica, id_paciente, estado);

CREATE INDEX ix_tratamiento_medico ON tratamientos (id_clinica, id_medico, estado);

CREATE UNIQUE INDEX uq_tratamiento_consulta_sin_receta ON tratamientos (id_clinica, id_consulta) WHERE id_receta IS NULL;

CREATE TABLE tratamiento_medicamentos (
    id_medicamento_plan BIGSERIAL NOT NULL,
    id_clinica BIGINT NOT NULL,
    id_tratamiento BIGINT NOT NULL,
    id_receta_detalle BIGINT NOT NULL,
    medicamento_nombre VARCHAR(200) NOT NULL,
    dosis VARCHAR(100) NOT NULL,
    via_administracion VARCHAR(30) NOT NULL,
    frecuencia_texto_receta VARCHAR(100) NOT NULL,
    duracion_texto_receta VARCHAR(100) NOT NULL,
    indicaciones TEXT,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    horas_locales JSONB NOT NULL,
    estado VARCHAR(20) DEFAULT 'ACTIVO' NOT NULL,
    suspendido_desde TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id_medicamento_plan),
    CONSTRAINT uq_tratamiento_medicamento_detalle UNIQUE (id_clinica, id_tratamiento, id_receta_detalle),
    CONSTRAINT ck_tratamiento_medicamento_fechas CHECK (fecha_fin >= fecha_inicio),
    CONSTRAINT ck_tratamiento_medicamento_estado CHECK (estado IN ('ACTIVO','SUSPENDIDO')),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_tratamiento) REFERENCES tratamientos (id_tratamiento),
    FOREIGN KEY(id_receta_detalle) REFERENCES receta_detalle (id_receta_detalle)
);

CREATE INDEX ix_tratamiento_medicamento_plan ON tratamiento_medicamentos (id_clinica, id_tratamiento);

CREATE TABLE tratamiento_dosis (
    id_dosis BIGSERIAL NOT NULL,
    id_clinica BIGINT NOT NULL,
    id_medicamento_plan BIGINT NOT NULL,
    programada_en_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    estado VARCHAR(20) DEFAULT 'PENDIENTE' NOT NULL,
    efectiva_en_utc TIMESTAMP WITH TIME ZONE,
    registrada_en_utc TIMESTAMP WITH TIME ZONE,
    cancelada_en_utc TIMESTAMP WITH TIME ZONE,
    alertas_evaluadas_en_utc TIMESTAMP WITH TIME ZONE,
    nota TEXT,
    PRIMARY KEY (id_dosis),
    CONSTRAINT uq_tratamiento_dosis_hora UNIQUE (id_clinica, id_medicamento_plan, programada_en_utc),
    CONSTRAINT ck_tratamiento_dosis_estado CHECK (estado IN ('PENDIENTE','INGERIDA','OMITIDA','POSPUESTA')),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_medicamento_plan) REFERENCES tratamiento_medicamentos (id_medicamento_plan)
);

CREATE INDEX ix_tratamiento_dosis_programada ON tratamiento_dosis (id_clinica, programada_en_utc, estado);

CREATE INDEX ix_tratamiento_dosis_alertas ON tratamiento_dosis (id_clinica, alertas_evaluadas_en_utc, programada_en_utc);

CREATE TABLE tratamiento_eventos (
    id_evento BIGSERIAL NOT NULL,
    id_clinica BIGINT NOT NULL,
    id_tratamiento BIGINT NOT NULL,
    id_medicamento_plan BIGINT,
    id_dosis BIGINT,
    accion VARCHAR(50) NOT NULL,
    estado_anterior VARCHAR(30),
    estado_nuevo VARCHAR(30),
    id_usuario BIGINT NOT NULL,
    rol_actor VARCHAR(100) NOT NULL,
    direccion_ip VARCHAR(45),
    nota TEXT,
    efectiva_en_utc TIMESTAMP WITH TIME ZONE,
    ocurrida_en_utc TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    idempotencia_hash VARCHAR(64),
    request_hash VARCHAR(64),
    respuesta_json JSONB,
    PRIMARY KEY (id_evento),
    CONSTRAINT uq_tratamiento_evento_idempotencia UNIQUE (id_clinica, id_usuario, id_dosis, idempotencia_hash),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_tratamiento) REFERENCES tratamientos (id_tratamiento),
    FOREIGN KEY(id_medicamento_plan) REFERENCES tratamiento_medicamentos (id_medicamento_plan),
    FOREIGN KEY(id_dosis) REFERENCES tratamiento_dosis (id_dosis),
    FOREIGN KEY(id_usuario) REFERENCES usuarios (id_usuario)
);

CREATE INDEX ix_tratamiento_evento_plan ON tratamiento_eventos (id_clinica, id_tratamiento, ocurrida_en_utc);

CREATE TABLE tratamiento_avisos (
    id_aviso BIGSERIAL NOT NULL,
    id_clinica BIGINT NOT NULL,
    id_tratamiento BIGINT NOT NULL,
    id_dosis BIGINT NOT NULL,
    id_usuario BIGINT NOT NULL,
    tipo VARCHAR(30) NOT NULL,
    canal VARCHAR(10) NOT NULL,
    titulo VARCHAR(200) NOT NULL,
    mensaje TEXT NOT NULL,
    programada_en_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    estado VARCHAR(15) DEFAULT 'PENDIENTE' NOT NULL,
    enviada_en_utc TIMESTAMP WITH TIME ZONE,
    leida_en_utc TIMESTAMP WITH TIME ZONE,
    intentos INTEGER DEFAULT '0' NOT NULL,
    ultimo_error VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id_aviso),
    CONSTRAINT uq_cu17_aviso UNIQUE (id_clinica, id_dosis, id_usuario, tipo, canal),
    CONSTRAINT ck_cu17_aviso_tipo CHECK (tipo IN ('RECORDATORIO','OMISION','RIESGO_ABANDONO')),
    CONSTRAINT ck_cu17_aviso_canal CHECK (canal IN ('WEB','PUSH')),
    CONSTRAINT ck_cu17_aviso_estado CHECK (estado IN ('PENDIENTE','ENVIADO','FALLIDO')),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_tratamiento) REFERENCES tratamientos (id_tratamiento),
    FOREIGN KEY(id_dosis) REFERENCES tratamiento_dosis (id_dosis),
    FOREIGN KEY(id_usuario) REFERENCES usuarios (id_usuario)
);

CREATE INDEX ix_cu17_aviso_usuario ON tratamiento_avisos (id_clinica, id_usuario, canal, created_at);

CREATE INDEX ix_cu17_aviso_pendiente ON tratamiento_avisos (id_clinica, canal, estado, programada_en_utc);

CREATE TABLE tratamiento_dispositivos (
    id_dispositivo BIGSERIAL NOT NULL,
    id_clinica BIGINT NOT NULL,
    id_usuario BIGINT NOT NULL,
    token_cifrado TEXT NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    plataforma VARCHAR(10) NOT NULL,
    activo BOOLEAN DEFAULT true NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id_dispositivo),
    CONSTRAINT uq_cu17_dispositivo UNIQUE (id_clinica, id_usuario, token_hash),
    CONSTRAINT ck_cu17_dispositivo_plataforma CHECK (plataforma IN ('ANDROID','IOS')),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_usuario) REFERENCES usuarios (id_usuario)
);

CREATE INDEX ix_cu17_dispositivo_usuario ON tratamiento_dispositivos (id_clinica, id_usuario, activo);

CREATE TABLE tratamiento_entregas_push (
    id_entrega BIGSERIAL NOT NULL,
    id_clinica BIGINT NOT NULL,
    id_aviso BIGINT NOT NULL,
    id_dispositivo BIGINT NOT NULL,
    estado VARCHAR(15) DEFAULT 'PENDIENTE' NOT NULL,
    intentos INTEGER DEFAULT '0' NOT NULL,
    proximo_intento_en_utc TIMESTAMP WITH TIME ZONE,
    ultimo_error VARCHAR(100),
    enviada_en_utc TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id_entrega),
    CONSTRAINT uq_cu17_entrega_push UNIQUE (id_clinica, id_aviso, id_dispositivo),
    CONSTRAINT ck_cu17_entrega_estado CHECK (estado IN ('PENDIENTE','ENVIADO','FALLIDO')),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_aviso) REFERENCES tratamiento_avisos (id_aviso),
    FOREIGN KEY(id_dispositivo) REFERENCES tratamiento_dispositivos (id_dispositivo)
);

CREATE INDEX ix_cu17_entrega_pendiente ON tratamiento_entregas_push (id_clinica, estado, proximo_intento_en_utc);

CREATE TABLE tratamiento_cursores (
    id_clinica BIGINT NOT NULL,
    id_tratamiento BIGINT NOT NULL,
    siguiente_fecha DATE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id_clinica, id_tratamiento),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_tratamiento) REFERENCES tratamientos (id_tratamiento)
);

CREATE FUNCTION cu17_eventos_inmutables() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Los eventos CU17 son inmutables'; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER cu17_eventos_inmutables BEFORE UPDATE OR DELETE ON tratamiento_eventos FOR EACH ROW EXECUTE FUNCTION cu17_eventos_inmutables();

INSERT INTO permisos (nombre,descripcion,modulo,accion,estado) SELECT 'treatments:read','Consultar tratamientos','treatments','read','ACTIVO' WHERE NOT EXISTS (SELECT 1 FROM permisos WHERE nombre='treatments:read');

INSERT INTO permisos (nombre,descripcion,modulo,accion,estado) SELECT 'treatments:write','Gestionar tratamientos','treatments','write','ACTIVO' WHERE NOT EXISTS (SELECT 1 FROM permisos WHERE nombre='treatments:write');

INSERT INTO permisos (nombre,descripcion,modulo,accion,estado) SELECT 'treatments:dose:record','Registrar dosis propias','treatments','dose:record','ACTIVO' WHERE NOT EXISTS (SELECT 1 FROM permisos WHERE nombre='treatments:dose:record');

INSERT INTO permisos (nombre,descripcion,modulo,accion,estado) SELECT 'treatments:notify:read','Consultar avisos propios','treatments','notify:read','ACTIVO' WHERE NOT EXISTS (SELECT 1 FROM permisos WHERE nombre='treatments:notify:read');

INSERT INTO rol_permisos (id_rol,id_permiso) SELECT r.id_rol,p.id_permiso FROM roles r JOIN permisos p ON p.nombre='treatments:read' WHERE UPPER(r.nombre)='MEDICO' AND NOT EXISTS (SELECT 1 FROM rol_permisos rp WHERE rp.id_rol=r.id_rol AND rp.id_permiso=p.id_permiso);

INSERT INTO rol_permisos (id_rol,id_permiso) SELECT r.id_rol,p.id_permiso FROM roles r JOIN permisos p ON p.nombre='treatments:write' WHERE UPPER(r.nombre)='MEDICO' AND NOT EXISTS (SELECT 1 FROM rol_permisos rp WHERE rp.id_rol=r.id_rol AND rp.id_permiso=p.id_permiso);

INSERT INTO rol_permisos (id_rol,id_permiso) SELECT r.id_rol,p.id_permiso FROM roles r JOIN permisos p ON p.nombre='treatments:notify:read' WHERE UPPER(r.nombre)='MEDICO' AND NOT EXISTS (SELECT 1 FROM rol_permisos rp WHERE rp.id_rol=r.id_rol AND rp.id_permiso=p.id_permiso);

INSERT INTO rol_permisos (id_rol,id_permiso) SELECT r.id_rol,p.id_permiso FROM roles r JOIN permisos p ON p.nombre='treatments:read' WHERE UPPER(r.nombre)='PACIENTE' AND NOT EXISTS (SELECT 1 FROM rol_permisos rp WHERE rp.id_rol=r.id_rol AND rp.id_permiso=p.id_permiso);

INSERT INTO rol_permisos (id_rol,id_permiso) SELECT r.id_rol,p.id_permiso FROM roles r JOIN permisos p ON p.nombre='treatments:dose:record' WHERE UPPER(r.nombre)='PACIENTE' AND NOT EXISTS (SELECT 1 FROM rol_permisos rp WHERE rp.id_rol=r.id_rol AND rp.id_permiso=p.id_permiso);

INSERT INTO rol_permisos (id_rol,id_permiso) SELECT r.id_rol,p.id_permiso FROM roles r JOIN permisos p ON p.nombre='treatments:notify:read' WHERE UPPER(r.nombre)='PACIENTE' AND NOT EXISTS (SELECT 1 FROM rol_permisos rp WHERE rp.id_rol=r.id_rol AND rp.id_permiso=p.id_permiso);

INSERT INTO alembic_version (version_num) VALUES ('cu17_tratamientos_013') RETURNING alembic_version.version_num;

-- Running upgrade cu17_tratamientos_013 -> 014_operaciones_dosis_cu17

CREATE TABLE tratamiento_operaciones_dosis (
    id_operacion BIGSERIAL NOT NULL,
    id_clinica BIGINT NOT NULL,
    id_tratamiento BIGINT NOT NULL,
    id_dosis BIGINT NOT NULL,
    id_usuario BIGINT NOT NULL,
    generacion BIGINT DEFAULT '1' NOT NULL,
    idempotencia_hash VARCHAR(64) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    estado VARCHAR(20) DEFAULT 'EN_CURSO' NOT NULL,
    respuesta_json JSONB,
    error_detail TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id_operacion),
    CONSTRAINT uq_tratamiento_operacion_idempotencia UNIQUE (id_clinica, id_usuario, id_dosis, idempotencia_hash),
    CONSTRAINT ck_tratamiento_operacion_estado CHECK (estado IN ('EN_CURSO','CONFIRMADA','RECHAZADA')),
    FOREIGN KEY(id_clinica) REFERENCES clinicas (id_clinica),
    FOREIGN KEY(id_tratamiento) REFERENCES tratamientos (id_tratamiento),
    FOREIGN KEY(id_dosis) REFERENCES tratamiento_dosis (id_dosis),
    FOREIGN KEY(id_usuario) REFERENCES usuarios (id_usuario)
);

CREATE UNIQUE INDEX uq_op_dosis_activa ON tratamiento_operaciones_dosis (id_clinica, id_dosis) WHERE estado = 'EN_CURSO';

CREATE INDEX ix_tratamiento_operacion_dosis ON tratamiento_operaciones_dosis (id_clinica, id_dosis);

ALTER TABLE tratamiento_dosis ADD COLUMN generacion BIGINT DEFAULT '1' NOT NULL;

INSERT INTO tratamiento_operaciones_dosis (  id_clinica, id_tratamiento, id_dosis, id_usuario, generacion,   idempotencia_hash, request_hash, estado, respuesta_json, created_at, updated_at) SELECT   id_clinica, id_tratamiento, id_dosis, id_usuario, 1,   idempotencia_hash, COALESCE(request_hash, ''), 'CONFIRMADA', respuesta_json, ocurrida_en_utc, ocurrida_en_utc FROM tratamiento_eventos WHERE accion = 'REGISTRAR_DOSIS' AND idempotencia_hash IS NOT NULL AND id_dosis IS NOT NULL;

UPDATE alembic_version SET version_num='014_operaciones_dosis_cu17' WHERE alembic_version.version_num = 'cu17_tratamientos_013';

-- Running upgrade 014_operaciones_dosis_cu17, backup01ab23cd -> cu17_backup_merge_015

DELETE FROM alembic_version WHERE alembic_version.version_num = '014_operaciones_dosis_cu17';

UPDATE alembic_version SET version_num='cu17_backup_merge_015' WHERE alembic_version.version_num = 'backup01ab23cd';

COMMIT;

-- Verificacion de solo lectura despues del COMMIT:
SELECT version_num AS alembic_revision FROM alembic_version;
SELECT count(*) AS tablas_cu17
FROM information_schema.tables
WHERE table_schema = current_schema()
  AND table_name IN (
    'tratamientos','tratamiento_medicamentos','tratamiento_dosis',
    'tratamiento_eventos','tratamiento_operaciones_dosis','tratamiento_avisos',
    'tratamiento_dispositivos','tratamiento_entregas_push','tratamiento_cursores'
  );
