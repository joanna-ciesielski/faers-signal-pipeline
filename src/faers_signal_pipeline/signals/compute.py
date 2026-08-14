"""Compute ranked signal statistics into the indexed serving table.

Reads deduplicated cases (current_cases pointers joined to staging),
resolves drug identity through drug_map using the SAME Python cleaning as
the mapper (one implementation, no SQL drift), builds case-level 2x2
tables, computes PRR/ROR/chi-square, and truncate-rebuilds ``signal_stats``
(fixed decision 2: precomputed, indexed serving tables) in one transaction.

Every results artifact this module produces is signal detection, not risk
quantification (see package docstring and docs/dedup-policy.md).
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import psycopg

from faers_signal_pipeline import __version__
from faers_signal_pipeline.db.loader import record_run
from faers_signal_pipeline.normalize.clean import candidate_names
from faers_signal_pipeline.quarter import Quarter
from faers_signal_pipeline.signals.contingency import (
    DEFAULT_MIN_COUNT,
    build_contingency,
)
from faers_signal_pipeline.signals.stats import chi_square, prr, ror

_SIGNALS_DDL = """
CREATE TABLE IF NOT EXISTS signal_stats (
    cutoff_quarter text NOT NULL,
    rxcui          text NOT NULL,
    pt             text NOT NULL,
    a              bigint NOT NULL,
    b              bigint NOT NULL,
    c              bigint NOT NULL,
    d              bigint NOT NULL,
    prr            double precision,
    prr_ci_low     double precision,
    prr_ci_high    double precision,
    ror            double precision,
    ror_ci_low     double precision,
    ror_ci_high    double precision,
    chi_square     double precision,
    PRIMARY KEY (cutoff_quarter, rxcui, pt)
);
CREATE INDEX IF NOT EXISTS signal_stats_rank_idx
    ON signal_stats (cutoff_quarter, chi_square DESC);
CREATE INDEX IF NOT EXISTS signal_stats_ror_rank_idx
    ON signal_stats (cutoff_quarter, ror_ci_low DESC);
"""

SIGNALS_REPORT_VERSION = 1
_ROUND = 6  # serving-boundary rounding: readable, stable across runs
TOP_N_IN_REPORT = 25


@dataclass(frozen=True, slots=True)
class SignalsOutcome:
    report: dict[str, object]
    report_path: Path
    rows_written: int


def _key_of(raw: str) -> str:
    candidates = candidate_names(raw)
    return candidates[0] if candidates else ""


def _case_drugs(conn: psycopg.Connection) -> tuple[pl.DataFrame, dict[str, int]]:
    """Distinct (caseid, rxcui) for current cases; unmapped rows counted."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cc.caseid, coalesce(d.prod_ai, ''), coalesce(d.drugname, ''),"
            " count(*)"
            " FROM current_cases cc"
            " JOIN stg_drug d ON d.quarter = cc.quarter AND d.primaryid = cc.primaryid"
            " GROUP BY 1, 2, 3"
        )
        rows = cur.fetchall()
        cur.execute("SELECT name_key, rxcui FROM drug_map WHERE status = 'matched'")
        rxcui_by_key: dict[str, str] = dict(cur.fetchall())

    mapped: list[tuple[str, str]] = []
    unmapped_rows = 0
    for caseid, prod_ai, drugname, count in rows:
        rxcui = rxcui_by_key.get(_key_of(prod_ai)) or rxcui_by_key.get(_key_of(drugname))
        if rxcui is None:
            unmapped_rows += count
            continue
        mapped.append((caseid, rxcui))
    frame = pl.DataFrame(
        mapped or None,
        schema={"caseid": pl.String, "rxcui": pl.String},
        orient="row",
    )
    return frame, {"unmapped_drug_rows_excluded": unmapped_rows}


def _case_reactions(conn: psycopg.Connection) -> pl.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT cc.caseid, r.pt"
            " FROM current_cases cc"
            " JOIN stg_reac r ON r.quarter = cc.quarter AND r.primaryid = cc.primaryid"
            " WHERE r.pt IS NOT NULL"
        )
        rows = cur.fetchall()
    return pl.DataFrame(rows or None, schema={"caseid": pl.String, "pt": pl.String}, orient="row")


def compute_signals(
    conn: psycopg.Connection,
    report_dir: Path,
    min_count: int = DEFAULT_MIN_COUNT,
) -> SignalsOutcome:
    """Build and persist the ranked signal table from current cases."""
    started_at = datetime.datetime.now(tz=datetime.UTC)
    with conn.cursor() as cur, conn.transaction():
        cur.execute(_SIGNALS_DDL)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM current_cases")
        row = cur.fetchone()
        total_cases = int(row[0]) if row is not None else 0
        cur.execute("SELECT max(quarter) FROM current_cases")
        row = cur.fetchone()
        cutoff = row[0] if row and row[0] else "none"

    case_drugs, drug_stats = _case_drugs(conn)
    case_reactions = _case_reactions(conn)
    contingency = build_contingency(
        case_drugs, case_reactions, total_cases=total_cases, min_count=min_count
    )

    records: list[tuple[object, ...]] = []
    for rxcui, pt, a, b, c, d in contingency.pairs.iter_rows():
        prr_est = prr(a, b, c, d)
        ror_est = ror(a, b, c, d)
        chi2 = chi_square(a, b, c, d)
        records.append(
            (
                cutoff,
                rxcui,
                pt,
                a,
                b,
                c,
                d,
                round(prr_est.value, _ROUND) if prr_est else None,
                round(prr_est.ci_low, _ROUND) if prr_est else None,
                round(prr_est.ci_high, _ROUND) if prr_est else None,
                round(ror_est.value, _ROUND) if ror_est else None,
                round(ror_est.ci_low, _ROUND) if ror_est else None,
                round(ror_est.ci_high, _ROUND) if ror_est else None,
                round(chi2, _ROUND) if chi2 is not None else None,
            )
        )

    with conn.cursor() as cur, conn.transaction():
        cur.execute("TRUNCATE signal_stats")
        with cur.copy(
            "COPY signal_stats (cutoff_quarter, rxcui, pt, a, b, c, d,"
            " prr, prr_ci_low, prr_ci_high, ror, ror_ci_low, ror_ci_high,"
            " chi_square) FROM STDIN"
        ) as copy:
            for record in records:
                copy.write_row(record)

    # Ranking: descending lower bound of the ROR 95% CI — the conservative
    # standard presentation. Raw chi-square ranking is dominated by tiny
    # perfect-overlap cells (b=0/c=0 pairs reach chi2 ~= N); the CI lower
    # bound suppresses them naturally (zero-cell pairs have no ROR at all,
    # wide small-a intervals sink). Decision recorded 2026-08-13 after
    # observing exactly that degeneracy on real two-quarter data.
    ranked = sorted(
        records,
        key=lambda r: (-(r[11] if isinstance(r[11], float) else -1.0), r[1], r[2]),
    )
    top = [
        {
            "rxcui": r[1],
            "pt": r[2],
            "a": r[3],
            "prr": r[7],
            "prr_ci": [r[8], r[9]],
            "ror": r[10],
            "ror_ci": [r[11], r[12]],
            "chi_square": r[13],
        }
        for r in ranked[:TOP_N_IN_REPORT]
        if isinstance(r[11], float)
    ]
    report: dict[str, object] = {
        "report_version": SIGNALS_REPORT_VERSION,
        "code_version": __version__,
        "cutoff_quarter": cutoff,
        "min_count": min_count,
        **contingency.stats,
        **drug_stats,
        "signal_rows_written": len(records),
        "top_by_ror_ci_low": top,
        "disclaimer": (
            "FAERS is spontaneous reporting: no denominators, duplicate and"
            " stimulated reports. These statistics are signal detection,"
            " not risk quantification, and are not medical advice."
        ),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "signals.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = Quarter.parse(cutoff) if cutoff != "none" else Quarter(2004, 1)
    record_run(
        conn,
        latest,
        kind="compute_signals",
        started_at=started_at,
        finished_at=datetime.datetime.now(tz=datetime.UTC),
        code_version=__version__,
        config_hash=f"signals-v1-min{min_count}",
        input_sha256=None,
        stats=report,
    )
    return SignalsOutcome(report=report, report_path=report_path, rows_written=len(records))
