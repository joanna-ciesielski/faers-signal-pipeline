"""CLI: apply pending plain-SQL migrations.

Usage:
    uv run python scripts/migrate.py

Requires DATABASE_URL. Idempotent: safe to run any number of times; an
edited already-applied migration file is refused (checksum drift).
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg

from faers_signal_pipeline.db.migrate import MigrationDriftError, apply_migrations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("error: DATABASE_URL must be set", file=sys.stderr)
        return 2
    with psycopg.connect(database_url) as conn:
        conn.autocommit = True
        try:
            report = apply_migrations(conn)
        except MigrationDriftError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(f"migrations: {report.total_migrations} total, {report.newly_applied} newly applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
