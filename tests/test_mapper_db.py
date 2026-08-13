"""Mapper integration tests against Postgres (isolated schema, offline).

The second-run-zero-API-calls invariant is gated here, mirroring the fetch
cache's zero-network invariant.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import psycopg
import pytest
from tests.conftest import build_quarter_zip, database_url
from tests.factories import row_line

from faers_signal_pipeline.normalize.mapper import map_drugs
from faers_signal_pipeline.normalize.rxnav import RxNavClient
from faers_signal_pipeline.pipeline import load_quarter
from faers_signal_pipeline.quarter import Quarter

DATABASE_URL = database_url()

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL not set (start Postgres via docker compose)"
)

QUARTER = Quarter(2026, 2)
TEST_SCHEMA = "pytest_mapper"

#: name -> rxcui served by the fake RxNav; anything absent is a no-match.
KNOWN = {
    "EXAMPLINE": "1001",
    "EXAMPLEDRUG": "1002",
    "METFORMIN": "6809",
    "IBUPROFEN": "5640",
}


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cur, connection.transaction():
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
            cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
            cur.execute(f"SET search_path TO {TEST_SCHEMA}")
        yield connection


def fake_client(calls: list[str] | None = None, fail: set[str] | None = None) -> RxNavClient:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("name", "")
        if calls is not None:
            calls.append(name)
        if fail and name in fail:
            return httpx.Response(500)
        rxcui = KNOWN.get(name)
        if rxcui is None:
            return httpx.Response(200, json={"idGroup": {"name": name}})
        return httpx.Response(200, json={"idGroup": {"rxnormId": [rxcui]}})

    return RxNavClient(
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://rxnav.test/REST",
        min_interval_seconds=0.0,
        max_retries=0,
        sleep=lambda _: None,
    )


def stage_quarter(conn: psycopg.Connection, tmp_path: Path) -> None:
    """Four drug rows: 2 mappable via prod_ai, 1 via drugname salt-strip,
    1 genuinely unmappable."""
    zip_path = build_quarter_zip(
        tmp_path / "faers_ascii_2026q2.zip",
        QUARTER,
        data_rows={
            "demo": [row_line("demo")],
            "drug": [
                row_line("drug"),  # prod_ai EXAMPLINE -> matched
                row_line("drug", drug_seq="2", drugname="IBUPROFEN", prod_ai=""),
                row_line(
                    "drug",
                    drug_seq="3",
                    drugname="METFORMIN HYDROCHLORIDE",
                    prod_ai="",
                ),
                row_line("drug", drug_seq="4", drugname="MYSTERY TONIC 5000", prod_ai=""),
            ],
        },
        deleted_lines=[" "],
    )
    load_quarter(conn, zip_path, QUARTER, report_dir=tmp_path / "r")


class TestMapping:
    def test_first_run_maps_and_reports(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        stage_quarter(conn, tmp_path)
        outcome = map_drugs(conn, fake_client(), report_dir=tmp_path / "rep")

        report = outcome.report
        assert report["total_drug_rows"] == 4
        assert report["mapped_rows"] == 3
        assert report["mapped_rate"] == 0.75
        assert report["meets_80pct_target"] is False
        assert report["mapped_via_prod_ai"] == 1
        assert report["mapped_via_drugname"] == 2
        assert report["unmapped_top"] == [{"drugname": "MYSTERY TONIC 5000", "rows": 1}]
        assert outcome.pending_lookups == 0
        assert json.loads(outcome.report_path.read_text()) == report

    def test_salt_strip_fallback_recorded(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        stage_quarter(conn, tmp_path)
        map_drugs(conn, fake_client(), report_dir=tmp_path / "rep")
        row = conn.execute(
            "SELECT rxcui, status, matched_via FROM drug_map"
            " WHERE name_key = 'METFORMIN HYDROCHLORIDE'"
        ).fetchone()
        assert row == ("6809", "matched", "salt_stripped")

    def test_no_match_is_cached_as_an_answer(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        stage_quarter(conn, tmp_path)
        map_drugs(conn, fake_client(), report_dir=tmp_path / "rep")
        row = conn.execute(
            "SELECT rxcui, status FROM drug_map WHERE name_key = 'MYSTERY TONIC 5000'"
        ).fetchone()
        assert row == (None, "no_match")

    def test_second_run_makes_zero_api_calls(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        stage_quarter(conn, tmp_path)
        map_drugs(conn, fake_client(), report_dir=tmp_path / "rep")

        calls: list[str] = []
        outcome = map_drugs(conn, fake_client(calls=calls), report_dir=tmp_path / "rep")
        assert calls == []  # the invariant: warm cache -> no network
        assert outcome.api_calls == 0
        assert outcome.report["mapped_rows"] == 3

    def test_interrupted_run_resumes_from_misses(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        # 5 distinct name keys are staged (EXAMPLINE, EXAMPLEDRUG,
        # IBUPROFEN, METFORMIN HYDROCHLORIDE, MYSTERY TONIC 5000).
        stage_quarter(conn, tmp_path)
        first = map_drugs(conn, fake_client(), report_dir=tmp_path / "rep", limit=2)
        assert first.api_calls == 2
        assert first.pending_lookups == 3  # limit-skipped names count as pending

        first_two = {key for (key,) in conn.execute("SELECT name_key FROM drug_map").fetchall()}
        calls: list[str] = []
        second = map_drugs(conn, fake_client(calls=calls), report_dir=tmp_path / "rep")
        assert second.api_calls == 3
        assert second.pending_lookups == 0
        # Nothing already cached was re-asked.
        assert first_two.isdisjoint(set(calls))

        again: list[str] = []
        third = map_drugs(conn, fake_client(calls=again), report_dir=tmp_path / "rep")
        assert again == []
        assert third.api_calls == 0

    def test_persistent_api_failure_parks_and_continues(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        stage_quarter(conn, tmp_path)
        outcome = map_drugs(
            conn,
            fake_client(fail={"IBUPROFEN"}),
            report_dir=tmp_path / "rep",
        )
        assert outcome.pending_lookups == 1
        # The failed name is absent from the cache -> retried next run.
        row = conn.execute("SELECT count(*) FROM drug_map WHERE name_key = 'IBUPROFEN'").fetchone()
        assert row == (0,)

        recovered = map_drugs(conn, fake_client(), report_dir=tmp_path / "rep")
        assert recovered.pending_lookups == 0
        assert recovered.report["mapped_rows"] == 3


class TestMapDrugsCli:
    def test_cli_precondition_exits(self) -> None:
        from map_drugs import main

        assert main(["--database-url", ""]) == 2
        assert main(["--database-url", DATABASE_URL, "--rate", "0"]) == 2

    def test_cli_nothing_staged_exits_2(self, conn: psycopg.Connection) -> None:
        from map_drugs import main

        separator = "&" if "?" in DATABASE_URL else "?"
        url = f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}"
        assert main(["--database-url", url]) == 2
