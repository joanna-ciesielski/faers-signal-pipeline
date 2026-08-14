"""Activities: all I/O lives here, wrapped around the Phase 1-4 stages.

Error taxonomy:
- ``QuarterLoadError`` (layout verification failed, poison file, DEMO
  structural failure) -> non-retryable ApplicationError: retrying cannot
  fix bad input; the quarter fails cleanly and a backfill batch continues.
- Everything else (network, DB availability) stays retryable under the
  workflow's RetryPolicy with backoff.

The RxNav outage contract (plan: "retry then degrade to unmapped without
failing the quarter"): the mapper already retries internally and parks
persistent failures; this activity therefore ALWAYS succeeds, returning
the pending count for the workflow to record.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import psycopg
from temporalio import activity
from temporalio.exceptions import ApplicationError

from faers_signal_pipeline.db.cases import merge_cases
from faers_signal_pipeline.fetch import FetchError, fetch_quarter
from faers_signal_pipeline.normalize.mapper import map_drugs
from faers_signal_pipeline.normalize.rxnav import DEFAULT_BASE_URL, RxNavClient
from faers_signal_pipeline.pipeline import QuarterLoadError, load_quarter
from faers_signal_pipeline.quarter import Quarter
from faers_signal_pipeline.signals.compute import compute_signals


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Everything an ingest needs; serialized into workflow history."""

    database_url: str
    cache_dir: str = "data/faers-cache"
    report_dir: str = "data/reports"
    fetch_base_url: str = "https://fis.fda.gov/content/Exports"
    rxnav_base_url: str = DEFAULT_BASE_URL
    rxnav_rate_per_second: float = 4.0
    allow_missing_deleted: bool = False
    #: Prepended to child workflow IDs. Empty in production (the bare
    #: ingest-{quarter} ID is the idempotency boundary); tests set a
    #: unique prefix so runs never collide with leftovers on a shared
    #: dev server.
    workflow_id_prefix: str = ""


@activity.defn
def fetch_activity(quarter_label: str, config: PipelineConfig) -> dict[str, Any]:
    quarter = Quarter.parse(quarter_label)
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
            result = fetch_quarter(
                quarter, Path(config.cache_dir), client, base_url=config.fetch_base_url
            )
    except FetchError as exc:  # transient: retryable by policy
        raise ApplicationError(str(exc), type="FetchError") from exc
    if not result.verification.ok:
        codes = ";".join(f.code for f in result.verification.findings)
        raise ApplicationError(
            f"{quarter_label}: layout verification failed ({codes})",
            type="LayoutVerificationError",
            non_retryable=True,
        )
    return {"sha256": result.sha256, "from_cache": result.from_cache}


@activity.defn
def load_activity(quarter_label: str, config: PipelineConfig) -> dict[str, Any]:
    quarter = Quarter.parse(quarter_label)
    zip_path = Path(config.cache_dir) / f"faers_ascii_{quarter.label}.zip"
    activity.heartbeat("load:start")
    try:
        with psycopg.connect(config.database_url) as conn:
            result = load_quarter(
                conn,
                zip_path,
                quarter,
                report_dir=Path(config.report_dir),
                allow_missing_deleted=config.allow_missing_deleted,
            )
    except QuarterLoadError as exc:
        raise ApplicationError(str(exc), type="QuarterLoadError", non_retryable=True) from exc
    activity.heartbeat("load:done")
    totals = result.report["totals"]
    if not result.ok:
        raise ApplicationError(
            f"{quarter_label}: structural table failure",
            type="QuarterLoadError",
            non_retryable=True,
        )
    return {"totals": totals}


@activity.defn
def merge_activity(config: PipelineConfig) -> dict[str, Any]:
    with psycopg.connect(config.database_url) as conn:
        resolution, _ = merge_cases(conn, report_dir=Path(config.report_dir))
    return {"stats": resolution.stats}


@activity.defn
def map_activity(config: PipelineConfig) -> dict[str, Any]:
    with (
        psycopg.connect(config.database_url) as conn,
        httpx.Client() as http,
    ):
        client = RxNavClient(
            http=http,
            base_url=config.rxnav_base_url,
            min_interval_seconds=1.0 / config.rxnav_rate_per_second,
        )
        outcome = map_drugs(conn, client, report_dir=Path(config.report_dir))
    # Degrade-not-fail: pending lookups are recorded, never fatal here.
    return {
        "api_calls": outcome.api_calls,
        "pending_lookups": outcome.pending_lookups,
        "mapped_rate": outcome.report.get("mapped_rate"),
    }


@activity.defn
def signals_activity(config: PipelineConfig) -> dict[str, Any]:
    with psycopg.connect(config.database_url) as conn:
        outcome = compute_signals(conn, report_dir=Path(config.report_dir))
    return {"signal_rows_written": outcome.rows_written}


ALL_ACTIVITIES: list[Callable[..., object]] = [
    fetch_activity,
    load_activity,
    merge_activity,
    map_activity,
    signals_activity,
]
