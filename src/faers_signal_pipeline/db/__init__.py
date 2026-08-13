"""Phase 1 staging storage: raw-fidelity staged tables + quarantine + runs.

Staging tables are generated from the era layout spec (single source of
truth); the fixed cross-cutting tables (``runs``, ``quarantine``,
``stg_deleted_cases``) live in ``schema.sql``. The formal serving schema,
roles, and audit log arrive in Phase 6 as plain-SQL migrations.
"""
