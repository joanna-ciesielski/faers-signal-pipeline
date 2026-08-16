"""Materialize case_versions + current_cases from staged quarters.

The merge is a truncate-and-rebuild over the union of everything staged —
order-independence by construction (the plan's gate): whatever order
quarters were loaded in, the same staged union produces byte-identical
tables. One transaction; a failed merge leaves the previous tables intact.

``current_cases`` is a pointer table (caseid -> winning caseversion,
quarter, primaryid): staging remains the single source of payload truth,
and downstream phases join on (quarter, primaryid). Memory note: only the
four key columns ever leave Postgres — full-history scale (~30M sightings)
stays comfortably in memory; payloads never do.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import polars as pl
import psycopg

from faers_signal_pipeline import __version__
from faers_signal_pipeline.db.loader import record_run
from faers_signal_pipeline.db.migrate import apply_migrations
from faers_signal_pipeline.dedup.resolve import Resolution, resolve_current
from faers_signal_pipeline.quarter import Quarter

MERGE_REPORT_VERSION = 1


def ensure_case_tables(conn: psycopg.Connection) -> None:
    """DDL lives in db/migrations (0002_cases.sql); apply is idempotent."""
    apply_migrations(conn)


def _read_frame(conn: psycopg.Connection, sql: str, columns: list[str]) -> pl.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return pl.DataFrame(rows or None, schema=dict.fromkeys(columns, pl.String), orient="row")


def merge_cases(conn: psycopg.Connection, report_dir: Path) -> tuple[Resolution, Path]:
    """Rebuild case_versions + current_cases from all staged quarters."""
    started_at = datetime.datetime.now(tz=datetime.UTC)
    ensure_case_tables(conn)

    sightings = _read_frame(
        conn,
        "SELECT caseid, caseversion, quarter, primaryid FROM stg_demo",
        ["caseid", "caseversion", "quarter", "primaryid"],
    )
    deletions = _read_frame(
        conn,
        "SELECT caseid, quarter FROM stg_deleted_cases",
        ["caseid", "quarter"],
    )

    resolution = resolve_current(sightings, deletions)

    history = (
        sightings.with_columns(pl.col("caseversion").cast(pl.Int64).alias("version_int"))
        .sort(["caseid", "version_int", "quarter", "primaryid"])
        .unique(subset=["caseid", "version_int", "quarter"], keep="last", maintain_order=True)
    )

    with conn.cursor() as cur, conn.transaction():
        cur.execute("TRUNCATE case_versions, current_cases")
        with cur.copy(
            "COPY case_versions (caseid, caseversion, version_int, quarter, primaryid) FROM STDIN"
        ) as copy:
            for caseid, caseversion, quarter, primaryid, version_int in history.select(
                "caseid", "caseversion", "quarter", "primaryid", "version_int"
            ).iter_rows():
                copy.write_row((caseid, caseversion, version_int, quarter, primaryid))
        with cur.copy(
            "COPY current_cases (caseid, caseversion, quarter, primaryid) FROM STDIN"
        ) as copy:
            for row in resolution.current.iter_rows():
                copy.write_row(row)

    quarters_staged: list[str] = sorted(sightings.get_column("quarter").unique().to_list())
    report: dict[str, object] = {
        "report_version": MERGE_REPORT_VERSION,
        "code_version": __version__,
        "quarters_staged": quarters_staged,
        "stats": resolution.stats,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "cases-merge.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    latest = Quarter.parse(quarters_staged[-1]) if quarters_staged else Quarter(2004, 1)
    record_run(
        conn,
        latest,
        kind="merge_cases",
        started_at=started_at,
        finished_at=datetime.datetime.now(tz=datetime.UTC),
        code_version=__version__,
        config_hash="dedup-v1",
        input_sha256=None,
        stats=report,
    )
    return resolution, report_path
