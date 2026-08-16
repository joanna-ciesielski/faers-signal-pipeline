-- RxNav drug-name cache (Phase 3).

CREATE TABLE IF NOT EXISTS drug_map (
    name_key    text PRIMARY KEY,
    rxcui       text,
    status      text NOT NULL,        -- 'matched' | 'no_match'
    matched_via text,                 -- 'exact' | 'salt_stripped'
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('matched', 'no_match'))
);
