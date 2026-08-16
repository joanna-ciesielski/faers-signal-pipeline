-- Cross-cutting tables (Phase 1). Staging tables for the seven FAERS
-- extracts are generated from the era layout spec at load time — see
-- README.md in this directory.

CREATE TABLE IF NOT EXISTS runs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind         text        NOT NULL,
    quarter      text        NOT NULL,
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz NOT NULL,
    code_version text        NOT NULL,
    config_hash  text        NOT NULL,
    input_sha256 text,
    stats        jsonb       NOT NULL
);

CREATE TABLE IF NOT EXISTS quarantine (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quarter       text        NOT NULL,
    source_member text        NOT NULL,
    scope         text        NOT NULL,      -- 'row' | 'file'
    locator       text,                      -- e.g. 'line:1234' for rows
    reason_codes  text        NOT NULL,      -- semicolon-joined machine codes
    detail        text        NOT NULL DEFAULT '',
    raw_payload   text        NOT NULL DEFAULT '',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS quarantine_quarter_idx ON quarantine (quarter);

CREATE TABLE IF NOT EXISTS stg_deleted_cases (
    quarter text NOT NULL,
    caseid  text NOT NULL,
    PRIMARY KEY (quarter, caseid)
);
