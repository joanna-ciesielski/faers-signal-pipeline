"""Transactional staging loader: parsed chunks -> Postgres, idempotently.

Semantics ("never partially loaded", made precise):

- Unit of atomicity = one (quarter, table). Each table load runs in a
  single transaction that first deletes that quarter's prior rows (staging
  *and* that member's quarantine rows), then COPYs clean rows and inserts
  quarantine rows. A structural failure mid-table rolls the whole table
  back and records a single file-level quarantine row instead.
- Re-running a quarter is therefore idempotent: delete-then-load converges
  to the same end state, loading zero duplicates (CI-gated invariant).
- DEMO loads first; child tables are checked for referential integrity
  against the primaryids that actually survived DEMO's contracts. If DEMO
  itself fails structurally, the quarter load aborts — children without a
  parent table would be unanchorable.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
import psycopg

from faers_signal_pipeline.contracts.certify import certify
from faers_signal_pipeline.contracts.frames import apply_contracts, split_join_orphans
from faers_signal_pipeline.db.migrate import apply_migrations
from faers_signal_pipeline.ingest.deleted import DeletedCases
from faers_signal_pipeline.ingest.reader import QuarantinedLine, ReaderError, iter_table_chunks
from faers_signal_pipeline.layout import TableSpec, tables_for_era
from faers_signal_pipeline.quarter import Quarter

#: Child tables load after demo, in a fixed order (determinism).
CHILD_TABLES = ("drug", "reac", "outc", "rpsr", "ther", "indi")


def connect(database_url: str) -> psycopg.Connection:
    """Open a psycopg connection (autocommit off; loader manages tx scope)."""
    return psycopg.connect(database_url)


def ensure_schema(conn: psycopg.Connection, quarter: Quarter) -> None:
    """Apply migrations, then generate per-table staging DDL (idempotent).

    Cross-cutting and derived tables live in plain-SQL migrations
    (db/migrations/); the seven ``stg_*`` staging tables stay generated
    from the era layout spec — layout.py is their single source of truth
    (see db/migrations/README.md).
    """
    apply_migrations(conn)
    with conn.cursor() as cur, conn.transaction():
        for table, spec in tables_for_era(quarter.era).items():
            columns = ",\n    ".join(f"{name} text" for name in spec.columns)
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS stg_{table} (\n"
                f"    quarter text NOT NULL,\n    {columns}\n)"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS stg_{table}_quarter_idx ON stg_{table} (quarter)"
            )


@dataclass(slots=True)
class TableLoadStats:
    """Per-table outcome, feeding the data-quality report."""

    table: str
    member: str
    status: str = "loaded"  # 'loaded' | 'failed_structural'
    rows_loaded: int = 0
    rows_quarantined: int = 0
    join_orphans: int = 0
    blank_lines: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    detail: str = ""


def _count_reasons(stats: TableLoadStats, quarantined: pl.DataFrame) -> None:
    for joined in quarantined.get_column("reasons").to_list():
        for reason in joined.split(";"):
            stats.reason_counts[reason] = stats.reason_counts.get(reason, 0) + 1


def _copy_frame(cur: psycopg.Cursor, table: str, quarter_label: str, frame: pl.DataFrame) -> None:
    columns = ", ".join(["quarter", *frame.columns])
    with cur.copy(f"COPY stg_{table} ({columns}) FROM STDIN") as copy:
        for row in frame.iter_rows():
            copy.write_row((quarter_label, *row))


def _insert_row_quarantine(
    cur: psycopg.Cursor,
    quarter_label: str,
    member: str,
    frame: pl.DataFrame,
    spec: TableSpec,
) -> None:
    """Quarantine contract-violating rows, preserving the raw field payload."""
    if frame.is_empty():
        return
    serialized = frame.select(
        pl.concat_str([pl.col(name).fill_null("") for name in spec.columns], separator="$").alias(
            "raw"
        ),
        pl.col("reasons"),
    )
    with cur.copy(
        "COPY quarantine (quarter, source_member, scope, locator, reason_codes,"
        " detail, raw_payload) FROM STDIN"
    ) as copy:
        for raw, reasons in serialized.iter_rows():
            copy.write_row((quarter_label, member, "row", None, reasons, "", raw))


def _insert_line_quarantine(
    cur: psycopg.Cursor, quarter_label: str, lines: tuple[QuarantinedLine, ...]
) -> None:
    if not lines:
        return
    with cur.copy(
        "COPY quarantine (quarter, source_member, scope, locator, reason_codes,"
        " detail, raw_payload) FROM STDIN"
    ) as copy:
        for line in lines:
            copy.write_row(
                (
                    quarter_label,
                    line.member,
                    "row",
                    f"line:{line.line_no}",
                    line.reason_code,
                    line.detail,
                    line.raw_line,
                )
            )


def _record_file_failure(
    conn: psycopg.Connection, quarter_label: str, member: str, detail: str
) -> None:
    with conn.cursor() as cur, conn.transaction():
        cur.execute(
            "DELETE FROM quarantine WHERE quarter = %s AND source_member = %s",
            (quarter_label, member),
        )
        cur.execute(
            "INSERT INTO quarantine (quarter, source_member, scope, reason_codes, detail)"
            " VALUES (%s, %s, 'file', 'structural_failure', %s)",
            (quarter_label, member, detail),
        )


def load_table(
    conn: psycopg.Connection,
    zip_path: Path,
    quarter: Quarter,
    table: str,
    member: str,
    spec: TableSpec,
    demo_primaryids: pl.Series | None,
    chunk_rows: int = 100_000,
) -> tuple[TableLoadStats, pl.Series | None]:
    """Load one table transactionally; returns stats (+ demo ids when table='demo')."""
    stats = TableLoadStats(table=table, member=member)
    collected_ids: list[pl.Series] = []
    try:
        with conn.cursor() as cur, conn.transaction():
            cur.execute(
                f"DELETE FROM stg_{table} WHERE quarter = %s",  # noqa: S608
                (quarter.label,),
            )
            cur.execute(
                "DELETE FROM quarantine WHERE quarter = %s AND source_member = %s",
                (quarter.label, member),
            )
            for chunk in iter_table_chunks(zip_path, member, spec, chunk_rows=chunk_rows):
                stats.blank_lines += chunk.blank_lines
                _insert_line_quarantine(cur, quarter.label, chunk.quarantined)
                stats.rows_quarantined += len(chunk.quarantined)
                for line in chunk.quarantined:
                    stats.reason_counts[line.reason_code] = (
                        stats.reason_counts.get(line.reason_code, 0) + 1
                    )

                result = apply_contracts(table, chunk.frame)
                _count_reasons(stats, result.quarantined)
                stats.rows_quarantined += result.quarantined.height
                _insert_row_quarantine(cur, quarter.label, member, result.quarantined, spec)

                good = result.good
                if demo_primaryids is not None:
                    join = split_join_orphans(good, demo_primaryids)
                    stats.join_orphans += join.orphans.height
                    stats.rows_quarantined += join.orphans.height
                    _count_reasons(stats, join.orphans)
                    _insert_row_quarantine(cur, quarter.label, member, join.orphans, spec)
                    good = join.good

                good = certify(table, good)
                _copy_frame(cur, table, quarter.label, good)
                stats.rows_loaded += good.height
                if table == "demo" and not good.is_empty():
                    collected_ids.append(good.get_column("primaryid"))
    except ReaderError as exc:
        stats.status = "failed_structural"
        stats.detail = str(exc)
        stats.rows_loaded = 0
        _record_file_failure(conn, quarter.label, member, str(exc))
        return stats, None

    ids = pl.concat(collected_ids) if collected_ids else None
    return stats, ids


def load_deleted_cases(
    conn: psycopg.Connection, quarter: Quarter, deleted: DeletedCases, member: str
) -> None:
    """Stage the quarter's deleted-cases list (idempotent, transactional)."""
    with conn.cursor() as cur, conn.transaction():
        cur.execute("DELETE FROM stg_deleted_cases WHERE quarter = %s", (quarter.label,))
        cur.execute(
            "DELETE FROM quarantine WHERE quarter = %s AND source_member = %s",
            (quarter.label, member),
        )
        with cur.copy("COPY stg_deleted_cases (quarter, caseid) FROM STDIN") as copy:
            for caseid in dict.fromkeys(deleted.caseids):
                copy.write_row((quarter.label, caseid))
        _insert_line_quarantine(cur, quarter.label, deleted.quarantined)


def record_run(
    conn: psycopg.Connection,
    quarter: Quarter,
    kind: str,
    started_at: datetime.datetime,
    finished_at: datetime.datetime,
    code_version: str,
    config_hash: str,
    input_sha256: str | None,
    stats: dict[str, object],
) -> None:
    with conn.cursor() as cur, conn.transaction():
        cur.execute(
            "INSERT INTO runs (kind, quarter, started_at, finished_at, code_version,"
            " config_hash, input_sha256, stats)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                kind,
                quarter.label,
                started_at,
                finished_at,
                code_version,
                config_hash,
                input_sha256,
                json.dumps(stats, sort_keys=True),
            ),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING always yields one row
            msg = "INSERT INTO runs returned no id"
            raise RuntimeError(msg)
        # Same transaction: a recorded run and its audit row are atomic.
        cur.execute(
            "INSERT INTO audit_log (action, quarter, object, details) VALUES (%s, %s, 'runs', %s)",
            (kind, quarter.label, json.dumps({"run_id": int(row[0])})),
        )
