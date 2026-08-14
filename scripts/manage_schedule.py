"""CLI: manage the quarterly ingestion Schedule.

Usage:
    uv run python scripts/manage_schedule.py create
    uv run python scripts/manage_schedule.py describe | pause | unpause | delete

Schedule: fires 15 Feb / 15 May / 15 Aug / 15 Nov at 06:00 UTC — roughly
2-3 weeks after FDA posts the previous calendar quarter. Overlap policy
SKIP (a still-running ingest suppresses the new fire); 30-day catch-up
window (a fire missed while the worker was down still runs if it comes
back within 30 days). The target quarter is derived from fire time inside
ScheduledIngestWorkflow.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)

from faers_signal_pipeline.orchestration import TASK_QUEUE
from faers_signal_pipeline.orchestration.activities import PipelineConfig
from faers_signal_pipeline.orchestration.workflows import ScheduledIngestWorkflow

SCHEDULE_ID = "quarterly-faers-ingest"


def quarterly_schedule(config: PipelineConfig, task_queue: str) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            ScheduledIngestWorkflow.run,
            args=[config],
            id="scheduled-ingest",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    month=(
                        ScheduleRange(2),
                        ScheduleRange(5),
                        ScheduleRange(8),
                        ScheduleRange(11),
                    ),
                    day_of_month=(ScheduleRange(15),),
                    hour=(ScheduleRange(6),),
                )
            ],
        ),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=timedelta(days=30),
        ),
    )


async def run(args: argparse.Namespace) -> int:
    client = await Client.connect(args.temporal)
    handle = client.get_schedule_handle(SCHEDULE_ID)
    if args.command == "create":
        config = PipelineConfig(database_url=os.environ["DATABASE_URL"])
        await client.create_schedule(SCHEDULE_ID, quarterly_schedule(config, args.task_queue))
        print(f"schedule {SCHEDULE_ID} created (Feb/May/Aug/Nov 15, 06:00 UTC)")
        return 0
    if args.command == "describe":
        description = await handle.describe()
        state = description.schedule.state
        print(f"{SCHEDULE_ID}: paused={state.paused} note={state.note!r}")
        for action_time in description.info.next_action_times[:4]:
            print(f"  next: {action_time.isoformat()}")
        return 0
    if args.command == "pause":
        await handle.pause(note="paused via manage_schedule.py")
    elif args.command == "unpause":
        await handle.unpause(note="unpaused via manage_schedule.py")
    elif args.command == "delete":
        await handle.delete()
    print(f"{SCHEDULE_ID}: {args.command} done")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create", "describe", "pause", "unpause", "delete"])
    parser.add_argument("--temporal", default=os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
    parser.add_argument("--task-queue", default=TASK_QUEUE)
    args = parser.parse_args(argv)
    if args.command == "create" and not os.environ.get("DATABASE_URL"):
        print("error: DATABASE_URL must be set to create the schedule", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
