"""CLI: map staged drug names to RxNorm RXCUIs via RxNav (cache-first).

Usage:
    uv run python scripts/map_drugs.py [--rate 4] [--limit N]

Requires DATABASE_URL (or --database-url). First run over fresh quarters
performs many API lookups (batched, resumable — safe to interrupt);
subsequent runs are zero-API-call unless new names appeared.

Exit codes:
    0  all name keys resolved; report written
    1  run completed but lookups remain (interrupted/--limit/API failures);
       re-run to continue
    2  precondition failure (no DB / nothing staged)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
import psycopg

from faers_signal_pipeline.normalize.mapper import map_drugs
from faers_signal_pipeline.normalize.rxnav import DEFAULT_BASE_URL, RxNavClient


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
    parser.add_argument("--rate", type=float, default=4.0, help="max RxNav requests per second")
    parser.add_argument(
        "--limit", type=int, default=None, help="max lookups this run (for partial runs)"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="override RxNav base URL")
    args = parser.parse_args(argv)
    if not args.database_url:
        print("error: no database URL (set DATABASE_URL or --database-url)", file=sys.stderr)
        return 2
    if args.rate <= 0:
        print("error: --rate must be positive", file=sys.stderr)
        return 2

    try:
        with (
            psycopg.connect(args.database_url) as conn,
            httpx.Client() as http,
        ):
            client = RxNavClient(
                http=http, base_url=args.base_url, min_interval_seconds=1.0 / args.rate
            )
            outcome = map_drugs(conn, client, report_dir=args.report_dir, limit=args.limit)
    except psycopg.OperationalError as exc:
        print(f"error: cannot connect to database: {exc}", file=sys.stderr)
        return 2
    except psycopg.errors.UndefinedTable:
        print("error: no staged drug rows found; run load_quarter first", file=sys.stderr)
        return 2

    summary = {key: value for key, value in outcome.report.items() if key not in {"unmapped_top"}}
    print(f"drug mapping -> report {outcome.report_path}")
    print(f"  {json.dumps(summary, sort_keys=True)}")
    if outcome.pending_lookups:
        print(
            f"  {outcome.pending_lookups} lookups pending (rerun to continue)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
