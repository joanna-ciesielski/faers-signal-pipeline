"""End-to-end staging tests against a real Postgres (localhost only).

Runs when DATABASE_URL is set (CI provides a pinned pgvector/pg16 service;
locally, docker compose up + your .env values). The idempotency test is the
CI-gated invariant from the plan: re-running a quarter loads zero duplicates.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from tests.conftest import build_quarter_zip, database_url
from tests.factories import row_line

from faers_signal_pipeline.pipeline import QuarterLoadError, load_quarter
from faers_signal_pipeline.quarter import Quarter

DATABASE_URL = database_url()

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL not set (start Postgres via docker compose)"
)

QUARTER = Quarter(2026, 2)

#: All test DB work happens in a dedicated schema, recreated per test, so a
#: developer's real staged data in the compose database is never touched.
TEST_SCHEMA = "pytest_stage"


def schema_scoped_url() -> str:
    """DATABASE_URL variant that pins search_path to the test schema."""
    separator = "&" if "?" in DATABASE_URL else "?"
    return f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL) as connection:
        # Autocommit: plain reads must never leave an implicit transaction
        # open (it would demote transaction() blocks to savepoints and
        # hold locks that deadlock the CLIs' separate connections).
        connection.autocommit = True
        with connection.cursor() as cur, connection.transaction():
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
            cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
            cur.execute(f"SET search_path TO {TEST_SCHEMA}")
        yield connection


def scalar(conn: psycopg.Connection, sql: str) -> object:
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        assert row is not None
        return row[0]


@pytest.fixture
def good_quarter_zip(tmp_path: Path) -> Path:
    return build_quarter_zip(
        tmp_path / "faers_ascii_2026q2.zip",
        QUARTER,
        data_rows={
            "demo": [
                row_line("demo"),
                row_line("demo", primaryid="1000000022", caseid="10000001", sex="M"),
                row_line("demo", primaryid="1000000033", caseid="10000002", sex="XX"),
            ],
            "drug": [row_line("drug"), row_line("drug", primaryid="9990000019")],
            "reac": [row_line("reac"), row_line("reac") + "$RAGGED"],
            "outc": [row_line("outc")],
            "rpsr": [row_line("rpsr")],
            "ther": [row_line("ther")],
            "indi": [row_line("indi")],
        },
        deleted_lines=[" ", "10172236", "10923325"],
    )


class TestQuarterLoad:
    def test_full_load_stages_quarantines_and_reports(
        self, conn: psycopg.Connection, good_quarter_zip: Path, tmp_path: Path
    ) -> None:
        result = load_quarter(conn, good_quarter_zip, QUARTER, report_dir=tmp_path / "r")
        assert result.ok

        # demo: 2 clean, 1 vocab violation (sex=XX) quarantined
        assert scalar(conn, "SELECT count(*) FROM stg_demo") == 2
        # drug: 1 clean, 1 join orphan
        assert scalar(conn, "SELECT count(*) FROM stg_drug") == 1
        # reac: 1 clean, 1 ragged line
        assert scalar(conn, "SELECT count(*) FROM stg_reac") == 1
        assert scalar(conn, "SELECT count(*) FROM stg_deleted_cases") == 2

        reasons = {
            r
            for (r,) in conn.execute(
                "SELECT reason_codes FROM quarantine ORDER BY reason_codes"
            ).fetchall()
        }
        assert any("vocab_violation:sex" in r for r in reasons)
        assert "join_orphan" in reasons
        assert "field_count_mismatch" in reasons

        report = result.report
        tables = report["tables"]
        assert isinstance(tables, dict)
        assert tables["demo"]["rows_loaded"] == 2
        assert tables["drug"]["join_orphans"] == 1
        assert report["deleted_cases"] == {
            "count": 2,
            "quarantined_lines": 0,
            "list_present": True,
        }
        assert result.report_path.exists()
        assert scalar(conn, "SELECT count(*) FROM runs") == 1

    def test_rerun_is_idempotent_zero_duplicates(
        self, conn: psycopg.Connection, good_quarter_zip: Path, tmp_path: Path
    ) -> None:
        first = load_quarter(conn, good_quarter_zip, QUARTER, report_dir=tmp_path / "r")
        counts_before = {
            t: scalar(conn, f"SELECT count(*) FROM stg_{t}")  # noqa: S608
            for t in ("demo", "drug", "reac", "outc", "rpsr", "ther", "indi")
        }
        q_before = scalar(conn, "SELECT count(*) FROM quarantine")

        second = load_quarter(conn, good_quarter_zip, QUARTER, report_dir=tmp_path / "r")
        counts_after = {
            t: scalar(conn, f"SELECT count(*) FROM stg_{t}")  # noqa: S608
            for t in ("demo", "drug", "reac", "outc", "rpsr", "ther", "indi")
        }
        assert counts_after == counts_before
        assert scalar(conn, "SELECT count(*) FROM quarantine") == q_before
        assert scalar(conn, "SELECT count(*) FROM stg_deleted_cases") == 2
        # Determinism: the DQ report artifact is byte-identical across runs.
        assert first.report_path.read_bytes() == second.report_path.read_bytes()
        # Both runs are recorded (lineage), but staged data never duplicates.
        assert scalar(conn, "SELECT count(*) FROM runs") == 2

    def test_structural_failure_rolls_back_table_and_records_file_quarantine(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        zip_path = build_quarter_zip(
            tmp_path / "faers_ascii_2026q2.zip",
            QUARTER,
            data_rows={"demo": [row_line("demo")], "outc": [row_line("outc")]},
            header_overrides={"outc": "PRIMARYID$CASEID$WRONG_COL"},
        )
        # Layout verification catches the bad header up front: nothing loads.
        with pytest.raises(QuarterLoadError, match="header_mismatch"):
            load_quarter(conn, zip_path, QUARTER, report_dir=tmp_path / "r")

    def test_missing_deleted_list_requires_explicit_override(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        zip_path = build_quarter_zip(
            tmp_path / "faers_ascii_2026q2.zip",
            QUARTER,
            data_rows={"demo": [row_line("demo")]},
            include_deleted=False,
        )
        with pytest.raises(QuarterLoadError, match="deleted-cases"):
            load_quarter(conn, zip_path, QUARTER, report_dir=tmp_path / "r")

        result = load_quarter(
            conn,
            zip_path,
            QUARTER,
            report_dir=tmp_path / "r",
            allow_missing_deleted=True,
        )
        assert result.ok
        assert result.report["deleted_cases"] == {
            "count": None,
            "quarantined_lines": 0,
            "list_present": False,
        }

    def test_mid_load_structural_failure_records_file_quarantine(
        self, conn: psycopg.Connection, good_quarter_zip: Path
    ) -> None:
        # Reaches the loader's own structural path (verification can't see a
        # member that goes missing/unreadable between verify and load).
        from faers_signal_pipeline.db.loader import ensure_schema, load_table
        from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES

        ensure_schema(conn, QUARTER)
        stats, ids = load_table(
            conn,
            good_quarter_zip,
            QUARTER,
            "outc",
            "ASCII/MISSING26Q2.txt",
            FAERS_2014Q3_TABLES["outc"],
            demo_primaryids=None,
        )
        assert stats.status == "failed_structural"
        assert ids is None
        assert scalar(conn, "SELECT count(*) FROM stg_outc") == 0
        assert scalar(conn, "SELECT count(*) FROM quarantine WHERE scope = 'file'") == 1

    def test_staged_rows_preserve_raw_values(
        self, conn: psycopg.Connection, good_quarter_zip: Path, tmp_path: Path
    ) -> None:
        load_quarter(conn, good_quarter_zip, QUARTER, report_dir=tmp_path / "r")
        row = conn.execute("SELECT primaryid, caseid, outc_cod, quarter FROM stg_outc").fetchone()
        assert row == ("1000000011", "10000000", "HO", "2026q2")


class TestLoadQuarterCli:
    def test_cli_exit_codes(
        self, conn: psycopg.Connection, good_quarter_zip: Path, tmp_path: Path
    ) -> None:
        from load_quarter import main

        cache_dir = good_quarter_zip.parent
        assert main(["not-a-quarter"]) == 2
        assert (
            main(
                [
                    "2026q2",
                    "--cache-dir",
                    str(tmp_path / "nowhere"),
                    "--database-url",
                    DATABASE_URL,
                ]
            )
            == 2
        )
        exit_code = main(
            [
                "2026q2",
                "--cache-dir",
                str(cache_dir),
                "--report-dir",
                str(tmp_path / "reports"),
                "--database-url",
                schema_scoped_url(),  # CLI opens its own conn: pin test schema
            ]
        )
        assert exit_code == 0
        report = json.loads((tmp_path / "reports" / "dq-2026q2.json").read_text())
        assert report["totals"]["rows_loaded"] > 0
