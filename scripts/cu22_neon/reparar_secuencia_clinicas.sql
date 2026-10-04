-- CU22N26V1: propuesta para revisión manual. NO EJECUTADA.
-- Pausar antes todas las escrituras a clinicas y los consumidores directos de
-- clinicas_id_clinica_seq. Confirmar proyecto/rama/base en SQL Editor.
-- Solo reinicia la secuencia de identidad; no modifica filas ni la PK.
BEGIN;
SET LOCAL lock_timeout = '3s';
LOCK TABLE public.clinicas IN ACCESS EXCLUSIVE MODE NOWAIT;

DO $reparar$
DECLARE
    row_count bigint;
    min_id bigint;
    max_id bigint;
    seq_last bigint;
    seq_called boolean;
    seq_increment bigint;
    seq_cache bigint;
BEGIN
    IF current_database() <> 'Telemedicina'
       OR pg_get_serial_sequence('public.clinicas', 'id_clinica')
          IS DISTINCT FROM 'public.clinicas_id_clinica_seq' THEN
        RAISE EXCEPTION 'Base o secuencia de clinicas distinta de la revisada';
    END IF;

    SELECT count(*), min(id_clinica), max(id_clinica)
      INTO row_count, min_id, max_id FROM public.clinicas;
    IF row_count <> 2 OR min_id <> 1 OR max_id <> 2 THEN
        RAISE EXCEPTION 'Los IDs de clinicas cambiaron; revisar antes de reparar';
    END IF;

    SELECT last_value, is_called INTO seq_last, seq_called
      FROM public.clinicas_id_clinica_seq;
    SELECT seqincrement, seqcache INTO seq_increment, seq_cache
      FROM pg_sequence WHERE seqrelid = 'public.clinicas_id_clinica_seq'::regclass;
    IF seq_increment IS DISTINCT FROM 1 OR seq_cache IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'Los parametros de la secuencia cambiaron';
    END IF;

    -- RESTART es transaccional y bloquea nextval concurrente. Si la secuencia
    -- ya avanzó más allá de los IDs existentes, no la retrocede.
    IF seq_last < max_id OR (seq_last = max_id AND NOT seq_called) THEN
        EXECUTE format(
            'ALTER TABLE public.clinicas ALTER COLUMN id_clinica RESTART WITH %s',
            max_id + 1
        );
    END IF;
END
$reparar$;
COMMIT;
