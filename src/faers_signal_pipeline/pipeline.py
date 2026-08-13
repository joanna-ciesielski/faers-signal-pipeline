"""Quarter load orchestration: verified zip -> staged tables + DQ report.

This is the Phase 1 spine: fetch verification is a precondition, DEMO
anchors referential integrity, children follow in fixed order, the deleted
list stages beside them, and every outcome lands in the DQ report and the
runs row. Temporal wraps this in Phase 5; nothing here depends on it.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

from faers_signal_pipeline import __version__
from faers_signal_pipeline.db.loader import (
    CHILD_TABLES,
    TableLoadStats,
    ensure_schema,
    load_deleted_cases,
    load_table,
    record_run,
)
from faers_signal_pipeline.fetch import VerificationReport, verify_layout
from faers_signal_pipeline.ingest.deleted import DeletedCases, parse_deleted_list
from faers_signal_pipeline.layout import tables_for_era
from faers_signal_pipeline.quarter import Quarter
from faers_signal_pipeline.report import build_report, write_report


class QuarterLoadError(RuntimeError):
    """The quarter could not be loaded at all (precondition or DEMO failure)."""


@dataclass(frozen=True, slots=True)
class QuarterLoadResult:
    """Outcome of one quarter load."""

    report: dict[str, object]
    report_path: Path
    ok: bool  # every table loaded (quarantines allowed; structural failures not)


def _config_hash(chunk_rows: int) -> str:
    payload = json.dumps({"chunk_rows": chunk_rows}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _read_manifest_sha(zip_path: Path) -> str | None:
    manifest_path = zip_path.with_suffix(".manifest.json")
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    sha = manifest.get("sha256")
    return sha if isinstance(sha, str) else None


def load_quarter(
    conn: psycopg.Connection,
    zip_path: Path,
    quarter: Quarter,
    report_dir: Path,
    *,
    allow_missing_deleted: bool = False,
    chunk_rows: int = 100_000,
) -> QuarterLoadResult:
    """Stage one verified quarter into Postgres and write its DQ report.

    Preconditions (fail fast, load nothing):
    - layout verification must pass (``verify_layout``);
    - the deleted-cases list must be present, unless the caller explicitly
      passes ``allow_missing_deleted=True`` (the recorded override for
      quarters that genuinely predate the Deleted/ folder).
    """
    verification: VerificationReport = verify_layout(zip_path, quarter)
    if not verification.ok:
        codes = ";".join(f.code for f in verification.findings)
        msg = f"{quarter.label}: layout verification failed ({codes})"
        raise QuarterLoadError(msg)
    if verification.deleted_member is None and not allow_missing_deleted:
        msg = (
            f"{quarter.label}: no deleted-cases list in archive; pass"
            " allow_missing_deleted=True only if this quarter genuinely"
            " predates the Deleted/ folder (recorded override)"
        )
        raise QuarterLoadError(msg)

    started_at = datetime.datetime.now(tz=datetime.UTC)
    ensure_schema(conn, quarter)
    specs = tables_for_era(quarter.era)

    demo_stats, demo_ids = load_table(
        conn,
        zip_path,
        quarter,
        "demo",
        verification.table_members["demo"],
        specs["demo"],
        demo_primaryids=None,
        chunk_rows=chunk_rows,
    )
    if demo_stats.status != "loaded":
        msg = f"{quarter.label}: DEMO failed structurally: {demo_stats.detail}"
        raise QuarterLoadError(msg)

    table_stats: list[TableLoadStats] = [demo_stats]
    for table in CHILD_TABLES:
        stats, _ = load_table(
            conn,
            zip_path,
            quarter,
            table,
            verification.table_members[table],
            specs[table],
            demo_primaryids=demo_ids,
            chunk_rows=chunk_rows,
        )
        table_stats.append(stats)

    deleted_count: int | None = None
    deleted_quarantined = 0
    if verification.deleted_member is not None:
        deleted: DeletedCases = parse_deleted_list(zip_path, verification.deleted_member)
        load_deleted_cases(conn, quarter, deleted, verification.deleted_member)
        deleted_count = len(deleted.caseids)
        deleted_quarantined = len(deleted.quarantined)

    config_hash = _config_hash(chunk_rows)
    report = build_report(
        quarter_label=quarter.label,
        input_sha256=_read_manifest_sha(zip_path),
        table_stats=table_stats,
        deleted_count=deleted_count,
        deleted_quarantined=deleted_quarantined,
        config_hash=config_hash,
        code_version=__version__,
    )
    report_path = write_report(report, report_dir)
    record_run(
        conn,
        quarter,
        kind="stage_quarter",
        started_at=started_at,
        finished_at=datetime.datetime.now(tz=datetime.UTC),
        code_version=__version__,
        config_hash=config_hash,
        input_sha256=_read_manifest_sha(zip_path),
        stats=report,
    )
    ok = all(stats.status == "loaded" for stats in table_stats)
    return QuarterLoadResult(report=report, report_path=report_path, ok=ok)
