-- Role model (see README.md). Roles are cluster-global and created
-- idempotently; grants are scoped to the current schema so per-schema
-- test databases get the same model.

DO $$
BEGIN
    BEGIN
        CREATE ROLE etl_writer NOLOGIN;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        CREATE ROLE readonly_web NOLOGIN;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        CREATE ROLE readonly_analyst NOLOGIN;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END;
$$;

DO $$
DECLARE
    s text := current_schema();
BEGIN
    EXECUTE format(
        'GRANT USAGE ON SCHEMA %I TO etl_writer, readonly_web, readonly_analyst', s);

    -- etl_writer: full DML everywhere, then audit_log narrowed to
    -- INSERT+SELECT (the trigger enforces append-only regardless).
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE'
        ' ON ALL TABLES IN SCHEMA %I TO etl_writer', s);
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO etl_writer', s);
    EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON %I.audit_log FROM etl_writer', s);

    -- readonly_analyst: read everything, write nothing.
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO readonly_analyst', s);

    -- readonly_web: explicit serving surface only (drug_profiles is
    -- granted in 0007 where the table is created).
    EXECUTE format('GRANT SELECT ON %I.signal_stats TO readonly_web', s);
    EXECUTE format('GRANT SELECT ON %I.drug_map TO readonly_web', s);
    EXECUTE format('GRANT SELECT ON %I.runs TO readonly_web', s);

    -- Tables created LATER by the migration-running role (the generated
    -- stg_* staging tables, 0007's drug_profiles) inherit the writer and
    -- analyst grants automatically. readonly_web never inherits: its
    -- surface is always an explicit allow-list.
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE,'
        ' DELETE, TRUNCATE ON TABLES TO etl_writer', s);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT USAGE, SELECT'
        ' ON SEQUENCES TO etl_writer', s);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES'
        ' TO readonly_analyst', s);
END;
$$;
