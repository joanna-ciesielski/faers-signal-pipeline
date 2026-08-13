"""CLI: stage one verified, cached FAERS quarter into Postgres.

Usage:
    uv run python scripts/load_quarter.py 2026q2 [--cache-dir data/faers-cache]

Requires DATABASE_URL (or --database-url), e.g.
    postgresql://faers:PASSWORD@127.0.0.1:5432/faers

Exit codes:
    0  all tables loaded (row-level quarantines are normal and reported)
    1  one or more tables failed structurally (see DQ report + quarantine)
    2  precondition failure: bad arguments, missing/unverified zip, no DB
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from faers_signal_pipeline.pipeline import QuarterLoadError, load_quarter
from faers_signal_pipeline.quarter import Quarter, QuarterFormatError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quarter", help="quarter to load, e.g. 2026q2")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.environ.get("FAERS_CACHE_DIR", "data/faers-cache")),
    )
    parser.add_argument(
        "--report-dir", type=Path, default=Path("data/reports"), help="DQ report output dir"
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres DSN (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--allow-missing-deleted",
        action="store_true",
        help=(
            "load a quarter whose archive has no deleted-cases list;"
            " only for quarters that genuinely predate the Deleted/ folder"
        ),
    )
    args = parser.parse_args(argv)

    try:
        quarter = Quarter.parse(args.quarter)
    except QuarterFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.database_url:
        print("error: no database URL (set DATABASE_URL or --database-url)", file=sys.stderr)
        return 2
    zip_path = args.cache_dir / f"faers_ascii_{quarter.label}.zip"
    if not zip_path.exists():
        print(
            f"error: {zip_path} not found; run scripts/fetch_quarter.py first",
            file=sys.stderr,
        )
        return 2

    try:
        with psycopg.connect(args.database_url) as conn:
            result = load_quarter(
                conn,
                zip_path,
                quarter,
                report_dir=args.report_dir,
                allow_missing_deleted=args.allow_missing_deleted,
            )
    except QuarterLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except psycopg.OperationalError as exc:
        print(f"error: cannot connect to database: {exc}", file=sys.stderr)
        return 2

    totals = result.report["totals"]
    print(f"{quarter.label}: staged -> report {result.report_path}")
    print(f"  totals: {json.dumps(totals, sort_keys=True)}")
    if result.ok:
        return 0
    print("  one or more tables FAILED structurally", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
