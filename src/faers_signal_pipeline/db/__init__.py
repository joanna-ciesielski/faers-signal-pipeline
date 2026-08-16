"""Phase 1 staging storage: raw-fidelity staged tables + quarantine + runs.

Staging tables are generated from the era layout spec (single source of
truth); everything else — cross-cutting tables, derived tables, roles,
the append-only audit log, and pgvector objects — lives in the plain-SQL
migrations under ``migrations/`` (runner: ``migrate.py``).
"""
