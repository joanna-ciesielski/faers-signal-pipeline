"""Cache-first drug mapping over staged DRUG rows.

Strategy per drug row: PROD_AI (active ingredient — cleaner vocabulary)
first, DRUGNAME as fallback; a row is mapped when either resolves. The
mapped rate is therefore **row-weighted** — the DoD's >=80% is measured
over drug rows, not distinct names.

Cache semantics (``drug_map``): every looked-up name key is stored with
status 'matched' or 'no_match' — both are answers, so a completed mapping
re-run performs **zero API calls** (asserted in tests, same invariant as
the fetch cache). Lookups are committed in batches: an interrupted run
resumes from the remaining misses. A persistently failing lookup is parked
(left absent) and counted as pending — never fails the run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

from faers_signal_pipeline import __version__
from faers_signal_pipeline.normalize.clean import candidate_names
from faers_signal_pipeline.normalize.rxnav import RxNavClient, RxNavError

_DRUG_MAP_DDL = """
CREATE TABLE IF NOT EXISTS drug_map (
    name_key    text PRIMARY KEY,
    rxcui       text,
    status      text NOT NULL,        -- 'matched' | 'no_match'
    matched_via text,                 -- 'exact' | 'salt_stripped'
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('matched', 'no_match'))
);
"""

MAP_REPORT_VERSION = 1
DEFAULT_BATCH_SIZE = 200
UNMAPPED_TOP_N = 50


def ensure_drug_map(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur, conn.transaction():
        cur.execute(_DRUG_MAP_DDL)


@dataclass(frozen=True, slots=True)
class MapOutcome:
    """Outcome of one mapping run."""

    report: dict[str, object]
    report_path: Path
    #: Name keys still unresolved after this run: parked API failures plus
    #: anything skipped by --limit or an interruption. >0 means "run again".
    pending_lookups: int
    api_calls: int  # keys successfully resolved (matched or no_match) this run


def _distinct_name_keys(conn: psycopg.Connection) -> list[str]:
    """Every cache key needed to judge all staged drug rows."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT name FROM ("
            " SELECT prod_ai AS name FROM stg_drug WHERE prod_ai IS NOT NULL"
            " UNION SELECT drugname FROM stg_drug WHERE drugname IS NOT NULL"
            ") names"
        )
        rows = cur.fetchall()
    keys = {candidates[0] for (raw,) in rows if (candidates := candidate_names(raw))}
    return sorted(keys)


def _missing_keys(conn: psycopg.Connection, keys: list[str]) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT name_key FROM drug_map")
        cached = {key for (key,) in cur.fetchall()}
    return [key for key in keys if key not in cached]


def _lookup_one(client: RxNavClient, key: str) -> tuple[str | None, str | None]:
    """Resolve one cache key: exact candidate, then salt-stripped fallback."""
    rxcui = client.lookup_rxcui(key)
    if rxcui is not None:
        return rxcui, "exact"
    for fallback in candidate_names(key)[1:]:
        rxcui = client.lookup_rxcui(fallback)
        if rxcui is not None:
            return rxcui, "salt_stripped"
    return None, None


def _flush_batch(
    conn: psycopg.Connection, batch: list[tuple[str, str | None, str, str | None]]
) -> None:
    if not batch:
        return
    with conn.cursor() as cur, conn.transaction():
        cur.executemany(
            "INSERT INTO drug_map (name_key, rxcui, status, matched_via)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT (name_key) DO NOTHING",
            batch,
        )
    batch.clear()


def _key_of(raw: str) -> str:
    candidates = candidate_names(raw)
    return candidates[0] if candidates else ""


def _coverage(conn: psycopg.Connection) -> dict[str, object]:
    """Row-weighted coverage plus the frequency-ranked unmapped tier.

    Cleaning happens in exactly one place (``clean.py``): rows are grouped
    in SQL, but every name key is computed by the same Python functions the
    lookup used — no SQL re-implementation to drift.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(prod_ai, ''), coalesce(drugname, ''), count(*)"
            " FROM stg_drug GROUP BY 1, 2"
        )
        pairs = cur.fetchall()
        cur.execute("SELECT name_key, status FROM drug_map")
        cache: dict[str, str] = dict(cur.fetchall())

    total_rows = mapped_rows = via_prod_ai = via_drugname = 0
    unmapped: dict[str, int] = {}
    for prod_ai, drugname, count in pairs:
        total_rows += count
        if cache.get(_key_of(prod_ai)) == "matched":
            mapped_rows += count
            via_prod_ai += count
        elif cache.get(_key_of(drugname)) == "matched":
            mapped_rows += count
            via_drugname += count
        elif drugname:
            unmapped[drugname] = unmapped.get(drugname, 0) + count

    top = sorted(unmapped.items(), key=lambda item: (-item[1], item[0]))[:UNMAPPED_TOP_N]
    rate = (mapped_rows / total_rows) if total_rows else 0.0
    return {
        "total_drug_rows": total_rows,
        "mapped_rows": mapped_rows,
        "mapped_rate": round(rate, 4),
        "meets_80pct_target": rate >= 0.80,
        "mapped_via_prod_ai": via_prod_ai,
        "mapped_via_drugname": via_drugname,
        "unmapped_top": [{"drugname": name, "rows": n} for name, n in top],
    }


def map_drugs(
    conn: psycopg.Connection,
    client: RxNavClient,
    report_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
) -> MapOutcome:
    """Resolve all missing name keys through the cache, then report coverage."""
    ensure_drug_map(conn)
    needed = _distinct_name_keys(conn)
    missing = _missing_keys(conn, needed)
    missing_total = len(missing)
    if limit is not None:
        missing = missing[:limit]

    api_calls = 0
    batch: list[tuple[str, str | None, str, str | None]] = []
    for key in missing:
        try:
            rxcui, via = _lookup_one(client, key)
        except RxNavError:
            continue  # parked (stays missing); retried on the next run
        api_calls += 1
        status = "matched" if rxcui is not None else "no_match"
        batch.append((key, rxcui, status, via))
        if len(batch) >= batch_size:
            _flush_batch(conn, batch)
    _flush_batch(conn, batch)
    # Everything not resolved this run — parked failures AND names beyond
    # --limit — remains pending; the CLI exits 1 until this reaches zero.
    pending = missing_total - api_calls

    coverage = _coverage(conn)
    report: dict[str, object] = {
        "report_version": MAP_REPORT_VERSION,
        "code_version": __version__,
        "distinct_name_keys": len(needed),
        "looked_up_this_run": api_calls,
        "pending_lookups": pending,
        **coverage,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "drug-map.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return MapOutcome(
        report=report, report_path=report_path, pending_lookups=pending, api_calls=api_calls
    )
