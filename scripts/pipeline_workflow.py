"""CLI: start an ingest or backfill workflow (a worker must be running).

Usage:
    uv run python scripts/pipeline_workflow.py ingest 2026q2
    uv run python scripts/pipeline_workflow.py backfill 2026q1 2026q2 [--max-concurrency 2]

Requires DATABASE_URL. A duplicate start of a running quarter is a no-op
(reported, exit 0) — the workflow ID is the idempotency boundary.

Exit codes: 0 completed (or duplicate no-op); 1 workflow failed; 2 preconditions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict

from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import WorkflowAlreadyStartedError

from faers_signal_pipeline.orchestration import TASK_QUEUE
from faers_signal_pipeline.orchestration.activities import PipelineConfig
from faers_signal_pipeline.orchestration.workflows import (
    BackfillWorkflow,
    IngestQuarterWorkflow,
    ingest_workflow_id,
)
from faers_signal_pipeline.quarter import Quarter, QuarterFormatError


async def run(args: argparse.Namespace, config: PipelineConfig) -> int:
    client = await Client.connect(args.temporal)
    if args.command == "ingest":
        label = args.quarters[0]
        try:
            handle = await client.start_workflow(
                IngestQuarterWorkflow.run,
                args=[label, config],
                id=ingest_workflow_id(label),
                task_queue=args.task_queue,
            )
        except WorkflowAlreadyStartedError:
            print(f"{label}: ingest already running - no-op (idempotent)")
            return 0
        result = await handle.result()
        print(f"{label}: ingest complete")
        print(f"  {json.dumps(asdict(result), sort_keys=True, default=str)}")
        return 0
    backfill_handle = await client.start_workflow(
        BackfillWorkflow.run,
        args=[args.quarters, config, args.max_concurrency],
        id=f"backfill-{args.quarters[0]}-{args.quarters[-1]}",
        task_queue=args.task_queue,
    )
    summary = await backfill_handle.result()
    print(f"backfill complete: {len(summary.succeeded)} succeeded, {len(summary.failed)} failed")
    print(f"  {json.dumps(asdict(summary), sort_keys=True)}")
    return 0 if not summary.failed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ingest", "backfill"])
    parser.add_argument("quarters", nargs="+", help="quarter labels, e.g. 2026q2")
    parser.add_argument("--temporal", default=os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
    parser.add_argument("--task-queue", default=TASK_QUEUE)
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument(
        "--allow-missing-deleted",
        action="store_true",
        help="pass through to load for quarters predating the Deleted/ folder",
    )
    args = parser.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("error: DATABASE_URL must be set", file=sys.stderr)
        return 2
    try:
        for label in args.quarters:
            Quarter.parse(label)
    except QuarterFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.command == "ingest" and len(args.quarters) != 1:
        print("error: ingest takes exactly one quarter", file=sys.stderr)
        return 2

    config = PipelineConfig(
        database_url=database_url,
        allow_missing_deleted=args.allow_missing_deleted,
    )
    try:
        return asyncio.run(run(args, config))
    except WorkflowFailureError as exc:
        print(f"error: workflow failed: {exc.cause}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
