"""End-to-end dedup merge tests against Postgres, including THE gate:
loading the same quarters in different orders produces identical tables.

Same isolation approach as test_pipeline_db: everything runs in a dedicated
schema, recreated per test, so real staged data is never touched.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from tests.conftest import build_quarter_zip, database_url
from tests.factories import row_line

from faers_signal_pipeline.db.cases import merge_cases
from faers_signal_pipeline.pipeline import load_quarter
from faers_signal_pipeline.quarter import Quarter

DATABASE_URL = database_url()

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL not set (start Postgres via docker compose)"
)

Q1 = Quarter(2026, 1)
Q2 = Quarter(2026, 2)

TEST_SCHEMA = "pytest_dedup"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cur, connection.transaction():
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
            cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
            cur.execute(f"SET search_path TO {TEST_SCHEMA}")
        yield connection


def _reset_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur, conn.transaction():
        cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
        cur.execute(f"SET search_path TO {TEST_SCHEMA}")


def make_q1(tmp_path: Path) -> Path:
    """Q1: case 100 v1; case 200 v1; case 300 v1. No deletions."""
    return build_quarter_zip(
        tmp_path / "faers_ascii_2026q1.zip",
        Q1,
        data_rows={
            "demo": [
                row_line("demo", primaryid="1001", caseid="100", caseversion="1"),
                row_line("demo", primaryid="2001", caseid="200", caseversion="1"),
                row_line("demo", primaryid="3001", caseid="300", caseversion="1"),
            ]
        },
        deleted_lines=[" "],
    )


def make_q2(tmp_path: Path) -> Path:
    """Q2: case 100 v2 (revision); case 400 v1 (new). Case 300 deleted."""
    return build_quarter_zip(
        tmp_path / "faers_ascii_2026q2.zip",
        Q2,
        data_rows={
            "demo": [
                row_line("demo", primaryid="1002", caseid="100", caseversion="2"),
                row_line("demo", primaryid="4001", caseid="400", caseversion="1"),
            ]
        },
        deleted_lines=[" ", "300"],
    )


def current_rows(conn: psycopg.Connection) -> list[tuple[str, ...]]:
    return sorted(
        conn.execute("SELECT caseid, caseversion, quarter, primaryid FROM current_cases").fetchall()
    )


def history_rows(conn: psycopg.Connection) -> list[tuple[str, ...]]:
    return sorted(
        conn.execute("SELECT caseid, caseversion, quarter, primaryid FROM case_versions").fetchall()
    )


EXPECTED_CURRENT = [
    ("100", "2", "2026q2", "1002"),
    ("200", "1", "2026q1", "2001"),
    ("400", "1", "2026q2", "4001"),
]

EXPECTED_HISTORY = [
    ("100", "1", "2026q1", "1001"),
    ("100", "2", "2026q2", "1002"),
    ("200", "1", "2026q1", "2001"),
    ("300", "1", "2026q1", "3001"),
    ("400", "1", "2026q2", "4001"),
]


class TestMergeEndToEnd:
    def test_two_quarter_merge(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        """Revision supersedes, deletion removes, history keeps everything."""
        load_quarter(conn, make_q1(tmp_path), Q1, report_dir=tmp_path / "r")
        load_quarter(conn, make_q2(tmp_path), Q2, report_dir=tmp_path / "r")
        resolution, report_path = merge_cases(conn, report_dir=tmp_path / "r")

        assert current_rows(conn) == EXPECTED_CURRENT
        assert history_rows(conn) == EXPECTED_HISTORY
        assert resolution.stats["deleted_cases"] == 1
        report = json.loads(report_path.read_text())
        assert report["quarters_staged"] == ["2026q1", "2026q2"]

    def test_order_independence_through_database(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """THE gate, end-to-end: q1-then-q2 and q2-then-q1 converge to the
        identical current_cases and case_versions content."""
        q1, q2 = make_q1(tmp_path), make_q2(tmp_path)

        load_quarter(conn, q1, Q1, report_dir=tmp_path / "a")
        load_quarter(conn, q2, Q2, report_dir=tmp_path / "a")
        _, report_a = merge_cases(conn, report_dir=tmp_path / "a")
        current_a, history_a = current_rows(conn), history_rows(conn)

        _reset_schema(conn)

        load_quarter(conn, q2, Q2, report_dir=tmp_path / "b")
        load_quarter(conn, q1, Q1, report_dir=tmp_path / "b")
        _, report_b = merge_cases(conn, report_dir=tmp_path / "b")
        current_b, history_b = current_rows(conn), history_rows(conn)

        assert current_a == current_b == EXPECTED_CURRENT
        assert history_a == history_b == EXPECTED_HISTORY
        # The merge report artifact is byte-identical too (determinism).
        assert report_a.read_bytes() == report_b.read_bytes()

    def test_remerge_is_idempotent(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        """Re-running the merge with unchanged staging changes nothing."""
        load_quarter(conn, make_q1(tmp_path), Q1, report_dir=tmp_path / "r")
        load_quarter(conn, make_q2(tmp_path), Q2, report_dir=tmp_path / "r")
        merge_cases(conn, report_dir=tmp_path / "r")
        first_current, first_history = current_rows(conn), history_rows(conn)

        merge_cases(conn, report_dir=tmp_path / "r")
        assert current_rows(conn) == first_current
        assert history_rows(conn) == first_history

    def test_reload_then_remerge_converges(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        """Re-loading a quarter (idempotent staging) then re-merging yields
        the same tables — the full pipeline is re-runnable end to end."""
        q1, q2 = make_q1(tmp_path), make_q2(tmp_path)
        load_quarter(conn, q1, Q1, report_dir=tmp_path / "r")
        load_quarter(conn, q2, Q2, report_dir=tmp_path / "r")
        merge_cases(conn, report_dir=tmp_path / "r")

        load_quarter(conn, q2, Q2, report_dir=tmp_path / "r")  # re-load
        merge_cases(conn, report_dir=tmp_path / "r")
        assert current_rows(conn) == EXPECTED_CURRENT
        assert history_rows(conn) == EXPECTED_HISTORY

    def test_current_case_payload_joinable(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        """current_cases pointers join back to full staged payload."""
        load_quarter(conn, make_q1(tmp_path), Q1, report_dir=tmp_path / "r")
        load_quarter(conn, make_q2(tmp_path), Q2, report_dir=tmp_path / "r")
        merge_cases(conn, report_dir=tmp_path / "r")
        row = conn.execute(
            "SELECT d.caseid, d.caseversion, d.sex FROM current_cases c"
            " JOIN stg_demo d ON d.quarter = c.quarter AND d.primaryid = c.primaryid"
            " WHERE c.caseid = '100'"
        ).fetchone()
        assert row == ("100", "2", "F")


class TestMergeCasesCli:
    def test_cli_merges_and_reports(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        from merge_cases import main

        load_quarter(conn, make_q1(tmp_path), Q1, report_dir=tmp_path / "r")
        separator = "&" if "?" in DATABASE_URL else "?"
        url = f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}"
        exit_code = main(["--report-dir", str(tmp_path / "r"), "--database-url", url])
        assert exit_code == 0
        report = json.loads((tmp_path / "r" / "cases-merge.json").read_text())
        assert report["stats"]["current_cases"] == 3

    def test_cli_no_database_url_exits_2(self) -> None:
        from merge_cases import main

        assert main(["--database-url", ""]) == 2

    def test_cli_nothing_staged_exits_2(self, conn: psycopg.Connection) -> None:
        from merge_cases import main

        separator = "&" if "?" in DATABASE_URL else "?"
        url = f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}"
        assert main(["--database-url", url]) == 2
