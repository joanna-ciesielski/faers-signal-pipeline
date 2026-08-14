"""Worker wiring: activities run in threads (they are sync, DB-bound)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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
) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[IngestQuarterWorkflow, BackfillWorkflow, ScheduledIngestWorkflow],
        activities=ALL_ACTIVITIES,
        activity_executor=activity_executor or ThreadPoolExecutor(max_workers=4),
    )
