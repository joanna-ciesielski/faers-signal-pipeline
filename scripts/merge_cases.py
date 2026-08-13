"""CLI: rebuild case_versions + current_cases from all staged quarters.

Usage:
    uv run python scripts/merge_cases.py [--report-dir data/reports]

Requires DATABASE_URL (or --database-url). Run after load_quarter for each
quarter; safe to re-run any time (truncate-and-rebuild, order-independent).

Exit codes: 0 merged; 2 precondition failure (no DB / nothing staged).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from faers_signal_pipeline.db.cases import merge_cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-dir", type=Path, default=Path("data/reports"), help="report output dir"
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres DSN (default: $DATABASE_URL)",
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        print("error: no database URL (set DATABASE_URL or --database-url)", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(args.database_url) as conn:
            resolution, report_path = merge_cases(conn, report_dir=args.report_dir)
    except psycopg.OperationalError as exc:
        print(f"error: cannot connect to database: {exc}", file=sys.stderr)
        return 2
    except psycopg.errors.UndefinedTable:
        print("error: no staged quarters found; run load_quarter first", file=sys.stderr)
        return 2

    print(f"cases merged -> report {report_path}")
    print(f"  stats: {json.dumps(resolution.stats, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
