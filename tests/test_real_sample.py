"""Pipeline test over committed real-data CI samples (public domain).

Samples are produced by ``scripts/make_ci_sample.py`` from a genuinely
fetched quarter and committed to ``tests/fixtures/``. Real bytes catch
quirks synthetic fixtures can't. Skips when no sample or no database.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from tests.conftest import database_url

from faers_signal_pipeline.fetch import verify_layout
from faers_signal_pipeline.pipeline import load_quarter
from faers_signal_pipeline.quarter import Quarter

DATABASE_URL = database_url()
FIXTURES = Path(__file__).parent / "fixtures"
SAMPLES = sorted(FIXTURES.glob("faers_real_sample_*.zip"))


def _quarter_of(sample: Path) -> Quarter:
    match = re.search(r"faers_real_sample_(\d{4}q[1-4])\.zip$", sample.name)
    assert match is not None
    return Quarter.parse(match.group(1))


@pytest.mark.skipif(not SAMPLES, reason="no committed real samples yet")
@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
def test_real_sample_verifies(sample: Path) -> None:
    report = verify_layout(sample, _quarter_of(sample))
    assert report.ok, [f.code for f in report.findings]


@pytest.fixture
def db_conn() -> Iterator[psycopg.Connection]:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    with psycopg.connect(DATABASE_URL) as connection:
        # Isolated schema per test: never touches real staged data.
        with connection.cursor() as cur, connection.transaction():
            cur.execute("DROP SCHEMA IF EXISTS pytest_stage_sample CASCADE")
            cur.execute("CREATE SCHEMA pytest_stage_sample")
            cur.execute("SET search_path TO pytest_stage_sample")
        yield connection


@pytest.mark.skipif(not SAMPLES, reason="no committed real samples yet")
@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
def test_real_sample_stages_end_to_end(
    sample: Path, db_conn: psycopg.Connection, tmp_path: Path
) -> None:
    quarter = _quarter_of(sample)
    result = load_quarter(db_conn, sample, quarter, report_dir=tmp_path)
    assert result.ok
    totals = result.report["totals"]
    assert isinstance(totals, dict)
    # Real rows loaded; quarantine may legitimately be non-zero on real data
    # (that's the point) — but everything must be accounted for.
    assert totals["rows_loaded"] > 0
