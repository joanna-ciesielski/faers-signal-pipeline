"""Per-quarter data-quality report: the honest summary of what happened.

Written as a deterministic JSON artifact (sorted keys, no timestamps inside
the payload — timestamps live on the runs row) so byte-identical inputs
produce byte-identical reports.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from faers_signal_pipeline.db.loader import TableLoadStats

REPORT_VERSION = 1


def build_report(
    quarter_label: str,
    input_sha256: str | None,
    table_stats: list[TableLoadStats],
    deleted_count: int | None,
    deleted_quarantined: int,
    config_hash: str,
    code_version: str,
) -> dict[str, object]:
    """Assemble the DQ report payload for one quarter load."""
    return {
        "report_version": REPORT_VERSION,
        "quarter": quarter_label,
        "input_sha256": input_sha256,
        "code_version": code_version,
        "config_hash": config_hash,
        "tables": {
            stats.table: {
                key: value for key, value in asdict(stats).items() if key not in {"table"}
            }
            for stats in table_stats
        },
        "deleted_cases": {
            "count": deleted_count,
            "quarantined_lines": deleted_quarantined,
            "list_present": deleted_count is not None,
        },
        "totals": {
            "rows_loaded": sum(s.rows_loaded for s in table_stats),
            "rows_quarantined": sum(s.rows_quarantined for s in table_stats),
            "join_orphans": sum(s.join_orphans for s in table_stats),
            "blank_lines": sum(s.blank_lines for s in table_stats),
            "tables_failed": sorted(s.table for s in table_stats if s.status != "loaded"),
        },
    }


def write_report(report: dict[str, object], report_dir: Path) -> Path:
    """Write the report artifact; returns its path."""
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"dq-{report['quarter']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
