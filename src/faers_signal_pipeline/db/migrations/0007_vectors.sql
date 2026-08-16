-- pgvector: deterministic per-drug safety-profile texts + embeddings
-- (Phase 6). The extension is installed database-wide into the public
-- schema (never into a work schema: dropping a test schema must not drop
-- the extension). All references are schema-qualified so they resolve
-- under any search_path.

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS drug_profiles (
    cutoff_quarter text NOT NULL,
    rxcui          text NOT NULL,
    display_name   text NOT NULL,
    profile_text   text NOT NULL,
    profile_sha256 text NOT NULL,
    built_at       timestamptz NOT NULL DEFAULT now(),
    embedding      public.vector(384),
    embedded_sha   text,
    model          text,
    embedded_at    timestamptz,
    PRIMARY KEY (cutoff_quarter, rxcui)
);

CREATE INDEX IF NOT EXISTS drug_profiles_embedding_hnsw
    ON drug_profiles USING hnsw (embedding public.vector_cosine_ops);

DO $$
DECLARE
    s text := current_schema();
BEGIN
    EXECUTE format('GRANT SELECT ON %I.drug_profiles TO readonly_web', s);
END;
$$;
