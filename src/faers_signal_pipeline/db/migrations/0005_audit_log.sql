-- Append-only audit trail (Phase 6). Every recorded run writes an audit
-- row in the same transaction (see db/loader.py record_run); mutation is
-- blocked by trigger for EVERY role, including the table owner.

CREATE TABLE IF NOT EXISTS audit_log (
    id      bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at      timestamptz NOT NULL DEFAULT now(),
    actor   text        NOT NULL DEFAULT current_user,
    action  text        NOT NULL,
    quarter text,
    object  text        NOT NULL,
    details jsonb       NOT NULL DEFAULT '{}'::jsonb
);

CREATE OR REPLACE FUNCTION audit_log_block_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS audit_log_no_mutation ON audit_log;
CREATE TRIGGER audit_log_no_mutation
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();

DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_block_mutation();
