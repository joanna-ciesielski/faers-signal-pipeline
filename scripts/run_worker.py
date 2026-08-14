"""CLI: run the pipeline worker against the Temporal dev server.

Usage:
    uv run python scripts/run_worker.py [--temporal 127.0.0.1:7233]

Runs until interrupted (Ctrl+C). Requires DATABASE_URL for activities.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from temporalio.client import Client

from faers_signal_pipeline.orchestration import TASK_QUEUE
from faers_signal_pipeline.orchestration.worker import build_worker


async def run(address: str, task_queue: str) -> None:
    client = await Client.connect(address)
    worker = build_worker(client, task_queue=task_queue)
    print(f"worker started: {address} task_queue={task_queue} (Ctrl+C to stop)")
    await worker.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temporal", default=os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
    parser.add_argument("--task-queue", default=TASK_QUEUE)
    args = parser.parse_args(argv)
    if not os.environ.get("DATABASE_URL"):
        print("error: DATABASE_URL must be set for activities", file=sys.stderr)
        return 2
    try:
        asyncio.run(run(args.temporal, args.task_queue))
    except KeyboardInterrupt:
        print("worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
