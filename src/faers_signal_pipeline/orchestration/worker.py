"""Worker wiring: activities run in threads (they are sync, DB-bound).

Shutdown semantics: the SDK's default ``graceful_shutdown_timeout`` is
ZERO — ``shutdown()`` immediately delivers cancellation to in-flight
activities, which for our sync activities lands at their final heartbeat
and throws away completed work (and, observed on slow CI runners, can
leave the attempt unreported so the workflow stalls until an activity
timeout). A worker restart should DRAIN, not cancel: the default window
below lets an in-flight activity finish and report normally, bounded so
a truly stuck activity cannot block shutdown forever.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker

from faers_signal_pipeline.orchestration import TASK_QUEUE
from faers_signal_pipeline.orchestration.activities import ALL_ACTIVITIES
from faers_signal_pipeline.orchestration.workflows import (
    BackfillWorkflow,
    IngestQuarterWorkflow,
    ScheduledIngestWorkflow,
)


def build_worker(
    client: Client,
    task_queue: str = TASK_QUEUE,
    activity_executor: ThreadPoolExecutor | None = None,
    graceful_shutdown_timeout: timedelta = timedelta(seconds=30),
) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[IngestQuarterWorkflow, BackfillWorkflow, ScheduledIngestWorkflow],
        activities=ALL_ACTIVITIES,
        activity_executor=activity_executor or ThreadPoolExecutor(max_workers=4),
        graceful_shutdown_timeout=graceful_shutdown_timeout,
    )
