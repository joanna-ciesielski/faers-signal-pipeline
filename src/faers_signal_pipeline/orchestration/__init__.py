"""Temporal orchestration of the quarterly pipeline.

Workflows contain deterministic logic only; activities do all I/O and are
individually idempotent at the database level (delete-then-load staging,
truncate-and-rebuild merge/signals, cache-first mapping). The workflow ID
``ingest-{quarter}`` is the idempotency boundary: a duplicate start of the
same quarter is rejected by Temporal as already-running — a no-op.
"""

TASK_QUEUE = "faers-pipeline"
