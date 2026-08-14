"""CLI: compute ranked disproportionality statistics into signal_stats.

Usage:
    uv run python scripts/compute_signals.py [--min-count 3]

Requires DATABASE_URL (or --database-url). Run after merge_cases and
map_drugs. Truncate-and-rebuild: deterministic, re-runnable.

Exit codes: 0 computed; 2 precondition failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from faers_signal_pipeline.signals.compute import compute_signals


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
    parser.add_argument(
        "--min-count", type=int, default=3, help="a-cell threshold (default 3, Evans 2001)"
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        print("error: no database URL (set DATABASE_URL or --database-url)", file=sys.stderr)
        return 2
    if args.min_count < 1:
        print("error: --min-count must be >= 1", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(args.database_url) as conn:
            outcome = compute_signals(conn, report_dir=args.report_dir, min_count=args.min_count)
    except psycopg.OperationalError as exc:
        print(f"error: cannot connect to database: {exc}", file=sys.stderr)
        return 2
    except psycopg.errors.UndefinedTable:
        print(
            "error: prerequisites missing; run load_quarter, merge_cases and map_drugs first",
            file=sys.stderr,
        )
        return 2

    summary = {
        key: value
        for key, value in outcome.report.items()
        if key not in {"top_by_ror_ci_low", "disclaimer"}
    }
    print(f"signals computed -> report {outcome.report_path}")
    print(f"  {json.dumps(summary, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
