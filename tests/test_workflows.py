"""Temporal orchestration tests, including the failure-injection suite.

Pure parts (fire-time mapping, schedule spec, workflow IDs) always run.
The workflow/failure-injection tests need BOTH a Postgres and a Temporal
dev server on loopback (docker compose locally; service + background
container in CI) and skip visibly otherwise — this build sandbox cannot
reach a Temporal server, so their verification happens on the maintainer
machine and in CI by design (recorded in the resume pack).

Failure injections covered, per the build plan:
- worker killed mid-quarter -> durable resume, completed activities never
  re-run (runs-table counts prove it);
- poison file -> that quarter fails cleanly, the backfill batch completes;
- RxNav outage -> mapper parks lookups, quarter completes degraded (pending
  counted), never fails;
- duplicate schedule fire -> second start of the same workflow ID is
  rejected: idempotent no-op.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import psycopg
import pytest
from tests.conftest import build_quarter_zip, database_url
from tests.corpus import CASES, CORPUS_RXCUIS
from tests.factories import row_line

from faers_signal_pipeline.fetch import sha256_of
from faers_signal_pipeline.orchestration.workflows import (
    ingest_workflow_id,
    quarter_for_fire_time,
)
from faers_signal_pipeline.quarter import Quarter

DATABASE_URL = database_url()
TEMPORAL_ADDRESS = "127.0.0.1:7233"
TEST_SCHEMA = "pytest_temporal"
QUARTER = Quarter(2026, 2)
Q1 = Quarter(2026, 1)


def _temporal_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 7233), timeout=1):
            return True
    except OSError:
        return False


TEMPORAL_UP = _temporal_reachable()


class TestPureParts:
    """Always-on: deterministic pieces need no server."""

    @pytest.mark.parametrize(
        ("year", "month", "expected"),
        [
            (2026, 2, "2025q4"),
            (2026, 5, "2026q1"),
            (2026, 8, "2026q2"),
            (2026, 11, "2026q3"),
            (2027, 2, "2026q4"),
        ],
    )
    def test_quarter_for_fire_time(self, year: int, month: int, expected: str) -> None:
        assert quarter_for_fire_time(year, month) == expected

    def test_ingest_workflow_id_is_quarter_scoped(self) -> None:
        assert ingest_workflow_id("2026q2") == "ingest-2026q2"

    def test_quarterly_schedule_spec(self) -> None:
        from faers_signal_pipeline.orchestration.activities import PipelineConfig
        from manage_schedule import quarterly_schedule

        schedule = quarterly_schedule(
            PipelineConfig(database_url="postgresql://x"), task_queue="tq"
        )
        calendar = schedule.spec.calendars[0]
        assert [r.start for r in calendar.month] == [2, 5, 8, 11]
        assert calendar.day_of_month[0].start == 15
        assert schedule.policy.catchup_window.days == 30


pytestmark_db = pytest.mark.skipif(
    not (DATABASE_URL and TEMPORAL_UP),
    reason="needs Postgres AND Temporal dev server on loopback (docker compose up)",
)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL) as connection:
        connection.autocommit = True
        with connection.cursor() as cur, connection.transaction():
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
            cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
            cur.execute(f"SET search_path TO {TEST_SCHEMA}")
        yield connection


def schema_url() -> str:
    separator = "&" if "?" in DATABASE_URL else "?"
    return f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}"


class _RxNavHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
        rxcui = CORPUS_RXCUIS.get(name)
        payload: dict[str, Any] = {"idGroup": {"name": name}}
        if rxcui is not None:
            payload = {"idGroup": {"rxnormId": [rxcui]}}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep test output clean


@pytest.fixture
def rxnav_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _RxNavHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/REST"
    server.shutdown()


def corpus_rows() -> dict[str, list[str]]:
    demo: list[str] = []
    drug: list[str] = []
    reac: list[str] = []
    for caseid, (drugs, reactions) in CASES.items():
        primaryid = f"{caseid}1"
        demo.append(row_line("demo", primaryid=primaryid, caseid=caseid, caseversion="1"))
        for seq, name in enumerate(drugs, start=1):
            drug.append(
                row_line(
                    "drug",
                    primaryid=primaryid,
                    caseid=caseid,
                    drug_seq=str(seq),
                    drugname=name,
                    prod_ai="",
                )
            )
        reac.extend(row_line("reac", primaryid=primaryid, caseid=caseid, pt=pt) for pt in reactions)
    return {"demo": demo, "drug": drug, "reac": reac}


def stage_cache(cache_dir: Path, quarter: Quarter, poison: bool = False) -> None:
    """Pre-place a quarter in the fetch cache (zip + valid manifest) so the
    fetch activity is a zero-network cache hit. poison=True writes a
    corrupt archive whose manifest sha still matches (verification fails)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / f"faers_ascii_{quarter.label}.zip"
    if poison:
        zip_path.write_bytes(b"this is not a zip archive")
    else:
        build_quarter_zip(zip_path, quarter, data_rows=corpus_rows(), deleted_lines=[" "])
    manifest = {
        "manifest_version": 2,
        "quarter": quarter.label,
        "url": None,
        "sha256": sha256_of(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "verification": {},
    }
    zip_path.with_suffix(".manifest.json").write_text(json.dumps(manifest))


def make_config(tmp_path: Path, rxnav_url: str) -> Any:
    from faers_signal_pipeline.orchestration.activities import PipelineConfig

    return PipelineConfig(
        database_url=schema_url(),
        cache_dir=str(tmp_path / "cache"),
        report_dir=str(tmp_path / "reports"),
        fetch_base_url="http://127.0.0.1:9/Exports",  # never reached: cache hit
        rxnav_base_url=rxnav_url,
        rxnav_rate_per_second=1000.0,
        workflow_id_prefix=f"t-{uuid.uuid4().hex[:6]}-",
    )


def runs_count(conn: psycopg.Connection, kind: str) -> int:
    try:
        row = conn.execute("SELECT count(*) FROM runs WHERE kind = %s", (kind,)).fetchone()
    except psycopg.errors.UndefinedTable:
        return 0  # activities have not created the schema yet
    assert row is not None
    return int(row[0])


@pytestmark_db
class TestFailureInjection:
    def test_ingest_end_to_end_via_temporal(
        self, conn: psycopg.Connection, tmp_path: Path, rxnav_server: str
    ) -> None:
        """Happy path through Temporal: all five stages, real worker."""
        from temporalio.client import Client

        from faers_signal_pipeline.orchestration.activities import PipelineConfig  # noqa: F401
        from faers_signal_pipeline.orchestration.worker import build_worker
        from faers_signal_pipeline.orchestration.workflows import IngestQuarterWorkflow

        stage_cache(tmp_path / "cache", QUARTER)
        config = make_config(tmp_path, rxnav_server)
        task_queue = f"tq-{uuid.uuid4().hex[:8]}"

        async def scenario() -> Any:
            client = await Client.connect(TEMPORAL_ADDRESS)
            worker = build_worker(client, task_queue=task_queue)
            async with worker:
                return await client.execute_workflow(
                    IngestQuarterWorkflow.run,
                    args=[QUARTER.label, config],
                    id=f"e2e-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        result = asyncio.run(asyncio.wait_for(scenario(), timeout=120))
        assert result.quarter == "2026q2"
        assert result.fetched_from_cache is True
        assert result.pending_lookups == 0
        assert result.signal_rows_written == 3  # the corpus's qualifying pairs
        assert runs_count(conn, "stage_quarter") == 1

    def test_rxnav_outage_degrades_without_failing(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """RxNav down (dead loopback port): quarter completes DEGRADED —
        pending lookups counted, zero signals, workflow succeeds."""
        from temporalio.client import Client

        from faers_signal_pipeline.orchestration.worker import build_worker
        from faers_signal_pipeline.orchestration.workflows import IngestQuarterWorkflow

        stage_cache(tmp_path / "cache", QUARTER)
        config = make_config(tmp_path, "http://127.0.0.1:9/REST")
        task_queue = f"tq-{uuid.uuid4().hex[:8]}"

        async def scenario() -> Any:
            client = await Client.connect(TEMPORAL_ADDRESS)
            worker = build_worker(client, task_queue=task_queue)
            async with worker:
                return await client.execute_workflow(
                    IngestQuarterWorkflow.run,
                    args=[QUARTER.label, config],
                    id=f"outage-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        result = asyncio.run(asyncio.wait_for(scenario(), timeout=180))
        assert result.pending_lookups > 0
        assert result.signal_rows_written == 0

    def test_poison_file_fails_quarter_but_backfill_completes(
        self, conn: psycopg.Connection, tmp_path: Path, rxnav_server: str
    ) -> None:
        from temporalio.client import Client

        from faers_signal_pipeline.orchestration.worker import build_worker
        from faers_signal_pipeline.orchestration.workflows import BackfillWorkflow

        stage_cache(tmp_path / "cache", Q1, poison=True)
        stage_cache(tmp_path / "cache", QUARTER)
        config = make_config(tmp_path, rxnav_server)
        task_queue = f"tq-{uuid.uuid4().hex[:8]}"

        async def scenario() -> Any:
            client = await Client.connect(TEMPORAL_ADDRESS)
            worker = build_worker(client, task_queue=task_queue)
            async with worker:
                return await client.execute_workflow(
                    BackfillWorkflow.run,
                    args=[[Q1.label, QUARTER.label], config, 2],
                    id=f"backfill-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        summary = asyncio.run(asyncio.wait_for(scenario(), timeout=180))
        assert summary.succeeded == [QUARTER.label]
        assert list(summary.failed) == [Q1.label]

    def test_duplicate_start_is_idempotent_noop(self, tmp_path: Path) -> None:
        """Duplicate schedule fire semantics: same workflow ID while running
        -> rejected as already started. No worker needed (stays running)."""
        from temporalio.client import Client
        from temporalio.exceptions import WorkflowAlreadyStartedError

        from faers_signal_pipeline.orchestration.workflows import IngestQuarterWorkflow

        config = make_config(tmp_path, "http://127.0.0.1:9/REST")
        task_queue = f"tq-{uuid.uuid4().hex[:8]}"
        workflow_id = f"ingest-dup-{uuid.uuid4().hex[:8]}"

        async def scenario() -> bool:
            client = await Client.connect(TEMPORAL_ADDRESS)
            handle = await client.start_workflow(
                IngestQuarterWorkflow.run,
                args=[QUARTER.label, config],
                id=workflow_id,
                task_queue=task_queue,
            )
            try:
                await client.start_workflow(
                    IngestQuarterWorkflow.run,
                    args=[QUARTER.label, config],
                    id=workflow_id,
                    task_queue=task_queue,
                )
            except WorkflowAlreadyStartedError:
                return True
            finally:
                await handle.terminate("test cleanup")
            return False

        assert asyncio.run(asyncio.wait_for(scenario(), timeout=60)) is True

    # FLAKE HISTORY (CI-only, slow runners; 3 occurrences 2026-08-15..17):
    # (1) hard task cancel abandoned in-flight attempts -> fixed by
    # draining via worker.shutdown(); (2) SDK graceful_shutdown_timeout
    # defaults to ZERO, so shutdown still cancelled mid-flight work ->
    # fixed by a 30 s drain window in build_worker. Both fixes are real
    # and stand on their own; the test STILL times out occasionally on
    # CPU-starved runners (never locally). The invariant it gates is too
    # valuable to delete and the residual nondeterminism lives below the
    # SDK surface, so THIS TEST ALONE retries (bounded, delayed - fresh
    # uuid task queue and workflow IDs make a rerun fully isolated).
    # Every other test in the suite runs zero-retry.
    @pytest.mark.flaky(reruns=2, reruns_delay=10)
    def test_worker_killed_mid_quarter_resumes_without_reprocessing(
        self, conn: psycopg.Connection, tmp_path: Path, rxnav_server: str
    ) -> None:
        """Kill the worker after the load activity has completed; a new
        worker resumes the workflow. The load activity is NEVER re-run
        (exactly one stage_quarter runs row) — durable progress."""
        from temporalio.client import Client

        from faers_signal_pipeline.orchestration.worker import build_worker
        from faers_signal_pipeline.orchestration.workflows import IngestQuarterWorkflow

        stage_cache(tmp_path / "cache", QUARTER)
        config = make_config(tmp_path, rxnav_server)
        task_queue = f"tq-{uuid.uuid4().hex[:8]}"

        async def scenario() -> Any:
            client = await Client.connect(TEMPORAL_ADDRESS)
            handle = await client.start_workflow(
                IngestQuarterWorkflow.run,
                args=[QUARTER.label, config],
                id=f"kill-{uuid.uuid4().hex[:8]}",
                task_queue=task_queue,
            )
            worker_a = build_worker(client, task_queue=task_queue)
            task_a = asyncio.create_task(worker_a.run())
            # Wait until the load stage has committed, then kill worker A.
            for _ in range(200):
                if await asyncio.to_thread(runs_count, conn, "stage_quarter") >= 1:
                    break
                await asyncio.sleep(0.25)
            else:
                raise AssertionError("load never completed under worker A")
            # Stop worker A at an activity boundary: shutdown() stops
            # polling and drains the in-flight activity (if any), so
            # the stop never abandons a started attempt. A hard mid-
            # flight crash is recovered by Temporal's timeout machinery
            # (heartbeat / start-to-close) — minutes-scale by design,
            # which a test cannot wait out. The invariant under test is
            # resume-from-durable-history without reprocessing, and
            # that is boundary-independent.
            await worker_a.shutdown()
            with contextlib.suppress(asyncio.CancelledError):
                await task_a
            # Worker B resumes from durable history.
            worker_b = build_worker(client, task_queue=task_queue)
            async with worker_b:
                return await handle.result()

        result = asyncio.run(asyncio.wait_for(scenario(), timeout=180))
        assert result.quarter == QUARTER.label
        # THE assertion: the completed load activity was not reprocessed.
        assert runs_count(conn, "stage_quarter") == 1
        assert result.signal_rows_written == 3
