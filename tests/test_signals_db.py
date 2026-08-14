"""End-to-end signals test: corpus zip -> stage -> merge -> map -> signals.

Always-on assertions cover the COUNTING (2x2 cells must equal the
hand-countable corpus expectations) and determinism; the derived statistics
are validated separately against maintainer goldens in test_signal_stats.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import psycopg
import pytest
from tests.conftest import build_quarter_zip, database_url
from tests.corpus import CASES, CORPUS_RXCUIS, EXPECTED_CELLS, TOTAL_CASES
from tests.factories import row_line

from faers_signal_pipeline.db.cases import merge_cases
from faers_signal_pipeline.normalize.mapper import map_drugs
from faers_signal_pipeline.normalize.rxnav import RxNavClient
from faers_signal_pipeline.pipeline import load_quarter
from faers_signal_pipeline.quarter import Quarter
from faers_signal_pipeline.signals.compute import compute_signals

DATABASE_URL = database_url()

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL not set (start Postgres via docker compose)"
)

QUARTER = Quarter(2026, 2)
TEST_SCHEMA = "pytest_signals"


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


def corpus_client() -> RxNavClient:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("name", "")
        rxcui = CORPUS_RXCUIS.get(name)
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


def corpus_zip(tmp_path: Path) -> Path:
    demo_rows: list[str] = []
    drug_rows: list[str] = []
    reac_rows: list[str] = []
    for caseid, (drugs, reactions) in CASES.items():
        primaryid = f"{caseid}1"
        demo_rows.append(row_line("demo", primaryid=primaryid, caseid=caseid, caseversion="1"))
        for seq, drug in enumerate(drugs, start=1):
            drug_rows.append(
                row_line(
                    "drug",
                    primaryid=primaryid,
                    caseid=caseid,
                    drug_seq=str(seq),
                    drugname=drug,
                    prod_ai="",
                )
            )
        reac_rows.extend(
            row_line("reac", primaryid=primaryid, caseid=caseid, pt=pt) for pt in reactions
        )
    return build_quarter_zip(
        tmp_path / "faers_ascii_2026q2.zip",
        QUARTER,
        data_rows={"demo": demo_rows, "drug": drug_rows, "reac": reac_rows},
        deleted_lines=[" "],
    )


def run_pipeline(conn: psycopg.Connection, tmp_path: Path) -> Path:
    load_quarter(conn, corpus_zip(tmp_path), QUARTER, report_dir=tmp_path / "r")
    merge_cases(conn, report_dir=tmp_path / "r")
    map_drugs(conn, corpus_client(), report_dir=tmp_path / "r")
    return tmp_path / "r"


class TestCorpusEndToEnd:
    def test_cells_match_hand_countable_corpus(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """THE counting gate: pipeline cells == corpus expectations, which
        the maintainer can verify by counting the worksheet table."""
        report_dir = run_pipeline(conn, tmp_path)
        outcome = compute_signals(conn, report_dir=report_dir)

        rows = conn.execute(
            "SELECT rxcui, pt, a, b, c, d FROM signal_stats ORDER BY rxcui, pt"
        ).fetchall()
        cells = {(rxcui, pt): (a, b, c, d) for rxcui, pt, a, b, c, d in rows}
        assert cells == EXPECTED_CELLS

        report = outcome.report
        assert report["total_cases"] == TOTAL_CASES
        assert report["signal_rows_written"] == len(EXPECTED_CELLS)
        # Case 1019's unmappable drug row is excluded and counted.
        assert report["unmapped_drug_rows_excluded"] == 1
        # 8 observed pairs fall below a>=3 (hand-countable from the corpus).
        assert report["below_threshold_pairs"] == 8

    def test_statistics_columns_populated(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        report_dir = run_pipeline(conn, tmp_path)
        compute_signals(conn, report_dir=report_dir)
        row = conn.execute(
            "SELECT prr, prr_ci_low, prr_ci_high, ror, ror_ci_low, ror_ci_high,"
            " chi_square FROM signal_stats WHERE rxcui = '900001' AND pt = 'Nausea'"
        ).fetchone()
        assert row is not None
        assert all(value is not None for value in row)
        prr, prr_lo, prr_hi, ror, ror_lo, ror_hi, chi2 = row
        assert prr_lo < prr < prr_hi
        assert ror_lo < ror < ror_hi
        assert chi2 > 0

    def test_recompute_is_deterministic_and_byte_identical(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """DoD gate: ranked signals byte-identical across runs."""
        report_dir = run_pipeline(conn, tmp_path)
        first = compute_signals(conn, report_dir=report_dir)
        first_bytes = first.report_path.read_bytes()
        first_rows = conn.execute("SELECT * FROM signal_stats ORDER BY rxcui, pt").fetchall()

        second = compute_signals(conn, report_dir=report_dir)
        assert second.report_path.read_bytes() == first_bytes
        assert (
            conn.execute("SELECT * FROM signal_stats ORDER BY rxcui, pt").fetchall() == first_rows
        )

    def test_report_carries_disclaimer(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        """Every results surface carries the plain-language disclaimer
        (standing product rule): the report artifact is a results surface."""
        report_dir = run_pipeline(conn, tmp_path)
        outcome = compute_signals(conn, report_dir=report_dir)
        disclaimer = outcome.report["disclaimer"]
        assert isinstance(disclaimer, str)
        assert "signal detection" in disclaimer
        assert "not medical advice" in disclaimer


class TestComputeSignalsCli:
    def test_cli_preconditions(self) -> None:
        from compute_signals import main

        assert main(["--database-url", ""]) == 2
        assert main(["--database-url", DATABASE_URL, "--min-count", "0"]) == 2

    def test_cli_computes(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        from compute_signals import main

        run_pipeline(conn, tmp_path)
        separator = "&" if "?" in DATABASE_URL else "?"
        url = f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}"
        exit_code = main(["--database-url", url, "--report-dir", str(tmp_path / "cli")])
        assert exit_code == 0
        assert (tmp_path / "cli" / "signals.json").exists()
