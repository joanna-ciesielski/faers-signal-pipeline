# Plain-SQL migrations

Numbered `NNNN_name.sql` files, applied in order by
`faers_signal_pipeline.db.migrate.apply_migrations` (CLI:
`scripts/migrate.py`). Applied versions are tracked in
`schema_migrations` with a SHA-256 of the file content; editing an
already-applied file is refused at the next apply (drift error). History
is immutable — schema changes are always NEW files.

Application is idempotent and cheap when up to date, so every pipeline
stage calls it defensively (the same "just works on a fresh clone"
behavior the old runtime DDL had), and it is safe under concurrency (a
per-schema advisory lock serializes appliers).

## What is deliberately NOT here

The seven `stg_*` staging tables (demo, drug, reac, outc, rpsr, ther,
indi) are generated at load time from the era layout spec in
`layout.py`. FAERS layouts drift across eras; the layout spec is the
single source of truth for those columns, and duplicating it into static
SQL would create exactly the schema-drift risk this project treats as a
cardinal sin. `ensure_schema` in `db/loader.py` owns that generation.

## Role model (0006, 0007)

- `etl_writer` — full DML on pipeline tables; INSERT-only on `audit_log`.
- `readonly_analyst` — SELECT on everything, including `quarantine`.
- `readonly_web` — SELECT on the serving surface only: `signal_stats`,
  `drug_map`, `drug_profiles`, `runs`. No staging, no quarantine, no
  audit: those can contain raw FAERS payloads, and the web tier must be
  unable to read them even if compromised.

Roles are cluster-global; grants are schema-scoped (issued via DO blocks
against `current_schema()`, so per-schema test databases get the same
model). `ALTER DEFAULT PRIVILEGES` covers tables created later by the
migration-running role (e.g. the generated `stg_*` tables) — in any
deployment where ETL runs as a different role, re-issue grants
accordingly (Phase 8 concern).

`audit_log` is append-only for everyone including superuser: a trigger
raises on UPDATE/DELETE/TRUNCATE. Grants alone cannot bind the table
owner; the trigger can.
