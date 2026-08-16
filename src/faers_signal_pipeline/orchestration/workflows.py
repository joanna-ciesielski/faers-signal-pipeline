"""Workflows: deterministic orchestration only — no I/O, no wall clocks.

``IngestQuarterWorkflow`` runs the five stages for one quarter. Its
workflow ID (``ingest-{quarter}``) is the idempotency boundary: Temporal
rejects a duplicate start of a running quarter (schedule double-fire =
no-op), and each activity is idempotent at the DB level, so a retried or
resumed workflow never double-processes.

``BackfillWorkflow`` fans out child IngestQuarter workflows with bounded
concurrency; one quarter's (non-retryable) failure is recorded in the
summary and the batch continues — the batch-level poison-file semantics.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from faers_signal_pipeline.orchestration.activities import (
        PipelineConfig,
        fetch_activity,
        load_activity,
        map_activity,
        merge_activity,
        signals_activity,
    )

#: Transient failures retry with backoff; QuarterLoadError and
#: LayoutVerificationError are raised non-retryable by the activities.
_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=5,
)

_SHORT = timedelta(minutes=30)
_LONG = timedelta(hours=2)


def ingest_workflow_id(quarter_label: str) -> str:
    return f"ingest-{quarter_label}"


@dataclass(frozen=True, slots=True)
class IngestResult:
    quarter: str
    fetched_from_cache: bool
    rows_loaded_totals: dict[str, Any]
    merge_stats: dict[str, Any]
    pending_lookups: int
    signal_rows_written: int


@workflow.defn
class IngestQuarterWorkflow:
    """fetch -> load -> merge -> map -> signals for one quarter."""

    @workflow.run
    async def run(self, quarter_label: str, config: PipelineConfig) -> IngestResult:
        fetched = await workflow.execute_activity(
            fetch_activity,
            args=[quarter_label, config],
            start_to_close_timeout=_LONG,
            retry_policy=_RETRY,
        )
        loaded = await workflow.execute_activity(
            load_activity,
            args=[quarter_label, config],
            start_to_close_timeout=_LONG,
            # The load activity heartbeats only bracket the call
            # (start/done), so this must exceed the worst-case
            # single-quarter load; per-table heartbeats are planned
            # alongside the full-history backfill (Phase 8 gate).
            heartbeat_timeout=timedelta(minutes=45),
            retry_policy=_RETRY,
        )
        merged = await workflow.execute_activity(
            merge_activity,
            args=[config],
            start_to_close_timeout=_SHORT,
            retry_policy=_RETRY,
        )
        mapped = await workflow.execute_activity(
            map_activity,
            args=[config],
            start_to_close_timeout=_LONG,
            retry_policy=_RETRY,
        )
        signals = await workflow.execute_activity(
            signals_activity,
            args=[config],
            start_to_close_timeout=_SHORT,
            retry_policy=_RETRY,
        )
        return IngestResult(
            quarter=quarter_label,
            fetched_from_cache=bool(fetched["from_cache"]),
            rows_loaded_totals=dict(loaded["totals"]),
            merge_stats=dict(merged["stats"]),
            pending_lookups=int(mapped["pending_lookups"]),
            signal_rows_written=int(signals["signal_rows_written"]),
        )


@dataclass(frozen=True, slots=True)
class BackfillSummary:
    succeeded: list[str]
    failed: dict[str, str]  # quarter -> failure type/message


@workflow.defn
class BackfillWorkflow:
    """Ingest many quarters, oldest first, with bounded concurrency."""

    @workflow.run
    async def run(
        self,
        quarter_labels: list[str],
        config: PipelineConfig,
        max_concurrency: int = 2,
    ) -> BackfillSummary:
        semaphore = asyncio.Semaphore(max_concurrency)
        succeeded: list[str] = []
        failed: dict[str, str] = {}

        async def ingest(label: str) -> None:
            async with semaphore:
                try:
                    await workflow.execute_child_workflow(
                        IngestQuarterWorkflow.run,
                        args=[label, config],
                        id=config.workflow_id_prefix + ingest_workflow_id(label),
                    )
                except (ChildWorkflowError, ActivityError, ApplicationError) as exc:
                    cause = exc.cause if exc.cause is not None else exc
                    failed[label] = f"{type(cause).__name__}: {cause}"
                else:
                    succeeded.append(label)

        await asyncio.gather(*(ingest(label) for label in sorted(quarter_labels)))
        return BackfillSummary(succeeded=sorted(succeeded), failed=failed)


def quarter_for_fire_time(year: int, month: int) -> str:
    """Deterministic map from a schedule fire date to the target quarter.

    The schedule fires mid-Feb/May/Aug/Nov, ~2-3 weeks after FDA posts the
    previous calendar quarter: Feb -> Q4 of prior year, May -> Q1,
    Aug -> Q2, Nov -> Q3.
    """
    if month >= 11:
        return f"{year}q3"
    if month >= 8:
        return f"{year}q2"
    if month >= 5:
        return f"{year}q1"
    return f"{year - 1}q4"


@workflow.defn
class ScheduledIngestWorkflow:
    """Schedule entry point: derives the target quarter from fire time."""

    @workflow.run
    async def run(self, config: PipelineConfig) -> IngestResult:
        now = workflow.now()
        label = quarter_for_fire_time(now.year, now.month)
        return await workflow.execute_child_workflow(
            IngestQuarterWorkflow.run,
            args=[label, config],
            id=config.workflow_id_prefix + ingest_workflow_id(label),
        )
