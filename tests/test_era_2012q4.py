"""FAERS_2012Q4 era (2012Q4-2014Q2): verification, staging, mixed-era merge.

Written before the era support they gate. Ground truth: the real
``faers_ascii_2013q1.zip`` inspected on 2026-08-16 — lowercase ``ascii/``
inner dir, ``Readme.doc`` (no ASC_NTS), per-table PDFs, NO Deleted/
folder, and headers that are a strict subset of the current era's
columns after the ``gndr_cod -> sex`` alias (DEMO 22 of 25, DRUG 19 of
20 — no ``prod_ai``, REAC 3 of 4 — no ``drug_rec_act``).

Invariants gated here:

- The 2012Q4-era spec verifies a real-shaped era archive and REJECTS an
  era-mismatched header (current-era file presented as 2013).
- Staging is created from the SUPERSET spec, so load order across eras
  cannot produce narrow tables: an era quarter loading FIRST on a fresh
  schema must not break a later current-era load.
- Era-absent columns (``prod_ai``, ``drug_rec_act``, ``age_grp``…) land
  as NULL; contracts and certification apply only to columns the era
  publishes.
- Mixed-era dedup: the same caseid seen in 2013q1 (v1) and 2026q2 (v2)
  resolves to the current-era version — the invariant full history
  depends on.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from tests.conftest import build_quarter_zip, database_url

from faers_signal_pipeline.layout import Era
from faers_signal_pipeline.quarter import Quarter

DATABASE_URL = database_url()
pytestmark_db = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not configured")

TEST_SCHEMA = "pytest_era2012q4"
Q2013 = Quarter(2013, 1)
Q2026 = Quarter(2026, 2)

#: Raw $-delimited rows in the REAL observed 2013Q1 column order.
DEMO_2013 = [
    "9001$700$1$I$20130101$$20130102$20130103$EXP$M-1$ACME$45$YR$F$Y$70$KG$20130104$$MD$US$US",
    "9002$701$1$I$20130105$$20130106$20130107$EXP$M-2$ACME$50$YR$M$Y$80$KG$20130108$$MD$US$US",
]
DRUG_2013 = [
    "9001$700$1$PS$ALPHA$1$ORAL$1 TAB$$$Y$$$$$1$MG$TAB$QD",
    "9002$701$1$PS$BETA$1$ORAL$1 TAB$$$Y$$$$$1$MG$TAB$QD",
]
REAC_2013 = [
    "9001$700$Nausea",
    "9002$701$Rash",
]


def era_zip_2013q1(destination: Path) -> Path:
    """Real-shaped 2012Q4-era archive: ascii/ dir, Readme.doc, no deleted."""
    return build_quarter_zip(
        destination,
        Q2013,
        data_rows={"demo": DEMO_2013, "drug": DRUG_2013, "reac": REAC_2013},
        include_deleted=False,
        subdir="ascii",
        doc_names=("Readme.doc",),
    )


class TestLayout:
    def test_era_mapping(self) -> None:
        assert Q2013.era is Era.FAERS_2012Q4
        assert Quarter(2014, 2).era is Era.FAERS_2012Q4
        assert Quarter(2014, 3).era is Era.FAERS_2014Q3
        assert Quarter(2012, 3).era is Era.LEGACY_AERS

    def test_2012q4_spec_matches_observed_headers(self) -> None:
        from faers_signal_pipeline.layout import FAERS_2012Q4_TABLES

        assert FAERS_2012Q4_TABLES["demo"].columns[:4] == (
            "primaryid",
            "caseid",
            "caseversion",
            "i_f_code",
        )
        assert "prod_ai" not in FAERS_2012Q4_TABLES["drug"].columns
        assert "drug_rec_act" not in FAERS_2012Q4_TABLES["reac"].columns
        assert FAERS_2012Q4_TABLES["demo"].aliases.get("gndr_cod") == "sex"

    def test_every_era_is_subset_of_staging_superset(self) -> None:
        """The invariant the shared staging tables depend on."""
        from faers_signal_pipeline.layout import (
            FAERS_2012Q4_TABLES,
            STAGING_SUPERSET_TABLES,
        )

        for table, spec in FAERS_2012Q4_TABLES.items():
            superset = set(STAGING_SUPERSET_TABLES[table].columns)
            assert set(spec.columns) <= superset, table

    def test_legacy_era_has_its_own_spec(self) -> None:
        """Graduated in Phase 8b: legacy AERS now resolves to its ISR-keyed
        spec (tests/test_era_legacy.py owns its coverage)."""
        from faers_signal_pipeline.layout import LEGACY_AERS_TABLES, tables_for_era

        assert tables_for_era(Era.LEGACY_AERS) is LEGACY_AERS_TABLES


class TestVerification:
    def test_real_shaped_era_zip_verifies(self, tmp_path: Path) -> None:
        from faers_signal_pipeline.fetch import verify_layout

        zip_path = era_zip_2013q1(tmp_path / "faers_ascii_2013q1.zip")
        report = verify_layout(zip_path, Q2013)
        assert report.ok, [f.code for f in report.findings]
        codes = {f.code for f in report.findings}
        assert "deleted_list_missing" in codes  # StrEnum values; era ships none

    def test_2012q4_header_variants_verify(self, tmp_path: Path) -> None:
        """Real 2012Q4 drift observed 2026-08-16: UTF-8 BOM on the DRUG
        header, ``lot_nbr`` for ``lot_num``, ``outc_code`` for
        ``outc_cod`` — all must normalize and verify."""
        from faers_signal_pipeline.fetch import verify_layout
        from faers_signal_pipeline.layout import DELIMITER, FAERS_2012Q4_TABLES

        drug_cols = [
            "lot_nbr" if c == "lot_num" else c for c in FAERS_2012Q4_TABLES["drug"].columns
        ]
        bom_as_latin1 = "\u00ef\u00bb\u00bf"
        zip_path = build_quarter_zip(
            tmp_path / "faers_ascii_2012q4.zip",
            Quarter(2012, 4),
            header_overrides={
                "drug": bom_as_latin1 + DELIMITER.join(drug_cols).upper(),
                "outc": "PRIMARYID$CASEID$OUTC_CODE",
            },
            include_deleted=False,
            subdir="ascii",
            doc_names=("Readme.doc",),
        )
        report = verify_layout(zip_path, Quarter(2012, 4))
        assert report.ok, [f.detail for f in report.findings if f.severity == "error"]

    def test_current_era_header_rejected_for_2013(self, tmp_path: Path) -> None:
        from faers_signal_pipeline.fetch import verify_layout
        from faers_signal_pipeline.layout import DELIMITER, FAERS_2014Q3_TABLES

        wrong_header = DELIMITER.join(FAERS_2014Q3_TABLES["demo"].columns).upper()
        zip_path = build_quarter_zip(
            tmp_path / "faers_ascii_2013q1.zip",
            Q2013,
            header_overrides={"demo": wrong_header},
            include_deleted=False,
            subdir="ascii",
            doc_names=("Readme.doc",),
        )
        report = verify_layout(zip_path, Q2013)
        assert not report.ok
        assert any(f.code == "header_mismatch" for f in report.findings)


@pytestmark_db
class TestMixedEraDatabase:
    @pytest.fixture
    def conn(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.autocommit = True
            with connection.cursor() as cur, connection.transaction():
                cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
                cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
                cur.execute(f"SET search_path TO {TEST_SCHEMA}")
            yield connection

    def scalar(self, conn: psycopg.Connection, sql: str) -> object:
        row = conn.execute(sql).fetchone()
        assert row is not None
        return row[0]

    def test_era_quarter_loads_with_null_era_absent_columns(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        from faers_signal_pipeline.pipeline import load_quarter

        zip_path = era_zip_2013q1(tmp_path / "q.zip")
        result = load_quarter(
            conn, zip_path, Q2013, report_dir=tmp_path / "r", allow_missing_deleted=True
        )
        assert result.ok
        assert self.scalar(conn, "SELECT count(*) FROM stg_demo") == 2
        assert self.scalar(conn, "SELECT count(*) FROM stg_drug WHERE prod_ai IS NULL") == 2
        assert self.scalar(conn, "SELECT count(*) FROM stg_demo WHERE age_grp IS NULL") == 2
        assert self.scalar(conn, "SELECT count(*) FROM stg_demo WHERE sex IN ('F','M')") == 2
        assert (
            self.scalar(
                conn,
                "SELECT count(*) FROM quarantine WHERE quarter = '2013q1' AND scope = 'row'",
            )
            == 0
        )

    def test_era_first_then_current_era_load_works(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """Fresh schema, 2013 loads FIRST: staging must still fit 2026."""
        from faers_signal_pipeline.pipeline import load_quarter

        load_quarter(
            conn,
            era_zip_2013q1(tmp_path / "a.zip"),
            Q2013,
            report_dir=tmp_path / "r",
            allow_missing_deleted=True,
        )
        current = build_quarter_zip(tmp_path / "b.zip", Q2026)
        result = load_quarter(conn, current, Q2026, report_dir=tmp_path / "r")
        assert result.ok

    def test_mixed_era_merge_latest_version_wins(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """caseid 700: v1 in 2013q1, v2 in 2026q2 -> current is the 2026 copy."""
        from tests.factories import row_line

        from faers_signal_pipeline.db.cases import merge_cases
        from faers_signal_pipeline.pipeline import load_quarter

        load_quarter(
            conn,
            era_zip_2013q1(tmp_path / "a.zip"),
            Q2013,
            report_dir=tmp_path / "r",
            allow_missing_deleted=True,
        )
        current = build_quarter_zip(
            tmp_path / "b.zip",
            Q2026,
            data_rows={
                "demo": [
                    row_line("demo", primaryid="7002", caseid="700", caseversion="2"),
                ],
                "drug": [row_line("drug", primaryid="7002", caseid="700")],
                "reac": [row_line("reac", primaryid="7002", caseid="700", pt="Nausea")],
            },
        )
        load_quarter(conn, current, Q2026, report_dir=tmp_path / "r")
        resolution, _ = merge_cases(conn, report_dir=tmp_path / "r")
        assert resolution.stats["current_cases"] == 2  # cases 700 (v2) + 701 (v1)
        row = conn.execute(
            "SELECT caseversion, quarter, primaryid FROM current_cases WHERE caseid = '700'"
        ).fetchone()
        assert row == ("2", "2026q2", "7002")
        row = conn.execute(
            "SELECT caseversion, quarter FROM current_cases WHERE caseid = '701'"
        ).fetchone()
        assert row == ("1", "2013q1")
