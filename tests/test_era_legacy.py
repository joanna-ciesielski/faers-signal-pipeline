"""Legacy AERS era (2004Q1-2012Q3): ISR-keyed identity, trailing-$ lines.

Written before the era support they gate. Ground truth: the real
``aers_ascii_2010q1.zip`` inspected on 2026-08-17 — uppercase ``.TXT``
members under lowercase ``ascii/``, ``Asc_nts.doc``, extra STAT/SIZE
members, no deleted lists, and DEMO keyed by ISR/CASE/I_F_COD/FOLL_SEQ
with children keyed by ISR only. Two facts measured on all 135,784 real
DEMO rows: EVERY data line carries a trailing ``$`` (24 split fields for
23 columns), and FOLL_SEQ is blank on 131,385 rows (initial reports and
many follow-ups alike; populated values are small integers 1..n).

Approved policy (maintainer, 2026-08-17):

- Identity mapping: ISR -> primaryid, CASE -> caseid,
  FOLL_SEQ -> caseversion with blank interpreted as version 0 (staging
  keeps the raw NULL; the derived "0" appears in case_versions /
  current_cases).
- Cross-era ordering: ANY FAERS-era sighting supersedes ANY legacy
  sighting of the same case (every FAERS-era quarter postdates every
  legacy quarter); within an era, the existing version-then-quarter
  rules stand.
"""

from __future__ import annotations

import itertools
import zipfile
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import psycopg
import pytest
from tests.conftest import build_quarter_zip, database_url

from faers_signal_pipeline.layout import Era
from faers_signal_pipeline.quarter import Quarter

DATABASE_URL = database_url()
pytestmark_db = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not configured")

TEST_SCHEMA = "pytest_era_legacy"
Q2010 = Quarter(2010, 1)

#: The REAL observed raw headers (pre-alias), uppercase as published.
RAW_HEADERS = {
    "demo": (
        "ISR$CASE$I_F_COD$FOLL_SEQ$IMAGE$EVENT_DT$MFR_DT$FDA_DT$REPT_COD$MFR_NUM"
        "$MFR_SNDR$AGE$AGE_COD$GNDR_COD$E_SUB$WT$WT_COD$REPT_DT$OCCP_COD$DEATH_DT"
        "$TO_MFR$CONFID$REPORTER_COUNTRY"
    ),
    "drug": "ISR$DRUG_SEQ$ROLE_COD$DRUGNAME$VAL_VBM$ROUTE$DOSE_VBM$DECHAL$RECHAL$LOT_NUM$EXP_DT$NDA_NUM",  # noqa: E501
    "reac": "ISR$PT",
    "outc": "ISR$OUTC_COD",
    "rpsr": "ISR$RPSR_COD",
    "ther": "ISR$DRUG_SEQ$START_DT$END_DT$DUR$DUR_COD",
    "indi": "ISR$DRUG_SEQ$INDI_PT",
}

#: Raw data lines, trailing ``$`` included — exactly as published.
DEMO_2010 = [
    "5001$800$I$$IMG1$20100101$$20100102$EXP$M-1$ACME$45$YR$F$Y$70$KG$20100103$MD$$$Y$UNITED STATES$",  # noqa: E501
    "5002$801$I$$IMG2$20100104$$20100105$EXP$M-2$ACME$50$YR$M$Y$80$KG$20100106$MD$$$Y$UNITED STATES$",  # noqa: E501
]
DRUG_2010 = [
    "5001$1$PS$ALPHA$1$ORAL$1 TAB$Y$$LOT1$$123456$",
    "5002$1$PS$BETA$1$ORAL$1 TAB$Y$$LOT2$$123457$",
]
REAC_2010 = [
    "5001$Nausea$",
    "5002$Rash$",
]


def legacy_zip(destination: Path, quarter: Quarter = Q2010) -> Path:
    return build_quarter_zip(
        destination,
        quarter,
        header_overrides=RAW_HEADERS,
        data_rows={"demo": DEMO_2010, "drug": DRUG_2010, "reac": REAC_2010},
        include_deleted=False,
        subdir="ascii",
        doc_names=("Asc_nts.doc",),
    )


class TestLayout:
    def test_legacy_spec_exists_and_matches_observed(self) -> None:
        from faers_signal_pipeline.layout import LEGACY_AERS_TABLES, tables_for_era

        assert tables_for_era(Era.LEGACY_AERS) is LEGACY_AERS_TABLES
        demo = LEGACY_AERS_TABLES["demo"]
        assert demo.columns[:4] == ("primaryid", "caseid", "i_f_code", "caseversion")
        assert demo.aliases["isr"] == "primaryid"
        assert demo.aliases["case"] == "caseid"
        assert demo.aliases["foll_seq"] == "caseversion"
        assert demo.aliases["gndr_cod"] == "sex"
        assert "caseversion" in demo.blank_ok
        assert demo.trailing_delimiter
        drug = LEGACY_AERS_TABLES["drug"]
        assert "caseid" not in drug.columns
        assert drug.aliases["isr"] == "primaryid"
        assert LEGACY_AERS_TABLES["ther"].aliases["drug_seq"] == "dsg_drug_seq"
        assert LEGACY_AERS_TABLES["indi"].aliases["drug_seq"] == "indi_drug_seq"

    def test_every_era_is_subset_of_staging_superset(self) -> None:
        from faers_signal_pipeline.layout import (
            FAERS_2012Q4_TABLES,
            LEGACY_AERS_EARLY_TABLES,
            LEGACY_AERS_TABLES,
            STAGING_SUPERSET_TABLES,
        )

        for era_tables in (
            FAERS_2012Q4_TABLES,
            LEGACY_AERS_TABLES,
            LEGACY_AERS_EARLY_TABLES,
        ):
            for table, spec in era_tables.items():
                superset = set(STAGING_SUPERSET_TABLES[table].columns)
                assert set(spec.columns) <= superset, table

    def test_all_eras_are_now_specified(self) -> None:
        from faers_signal_pipeline.layout import tables_for_era

        for era in Era:
            assert tables_for_era(era)

    def test_early_legacy_era_mapping_and_spec(self) -> None:
        """2004Q1-2005Q2 DEMO ends at CONFID (no REPORTER_COUNTRY) —
        boundary observed on the real archive sweep, 2026-08-17."""
        from faers_signal_pipeline.layout import LEGACY_AERS_EARLY_TABLES, tables_for_era

        assert Quarter(2004, 1).era is Era.LEGACY_AERS_EARLY
        assert Quarter(2005, 2).era is Era.LEGACY_AERS_EARLY
        assert Quarter(2005, 3).era is Era.LEGACY_AERS
        early_demo = tables_for_era(Era.LEGACY_AERS_EARLY)["demo"]
        assert early_demo is LEGACY_AERS_EARLY_TABLES["demo"]
        assert early_demo.columns[-1] == "confid"
        assert "reporter_country" not in early_demo.columns
        assert early_demo.blank_ok == frozenset({"caseversion"})
        assert Era.LEGACY_AERS_EARLY.is_legacy
        assert Era.LEGACY_AERS.is_legacy
        assert not Era.FAERS_2014Q3.is_legacy

    def test_early_legacy_zip_verifies(self, tmp_path: Path) -> None:
        from faers_signal_pipeline.fetch import verify_layout

        early = Quarter(2004, 1)
        headers = dict(RAW_HEADERS)
        headers["demo"] = headers["demo"].rsplit("$REPORTER_COUNTRY", 1)[0]
        zip_path = build_quarter_zip(
            tmp_path / "faers_ascii_2004q1.zip",
            early,
            header_overrides=headers,
            include_deleted=False,
            subdir="ascii",
            doc_names=("Asc_nts.doc",),
        )
        report = verify_layout(zip_path, early)
        assert report.ok, [f.detail for f in report.findings if f.severity == "error"]

    def test_legacy_url_candidates_use_aers_prefix(self) -> None:
        base = "https://fis.fda.gov/content/Exports"
        legacy = Quarter(2010, 1).zip_url_candidates(base)
        assert legacy[0].endswith("/aers_ascii_2010q1.zip")
        assert any(url.endswith("/aers_ascii_2010Q1.zip") for url in legacy)
        modern = Quarter(2013, 1).zip_url_candidates(base)
        assert all("/faers_ascii_" in url for url in modern)


class TestReader:
    def test_trailing_delimiter_lines_parse(self, tmp_path: Path) -> None:
        from faers_signal_pipeline.ingest.reader import iter_table_chunks
        from faers_signal_pipeline.layout import LEGACY_AERS_TABLES

        zip_path = legacy_zip(tmp_path / "faers_ascii_2010q1.zip")
        member = f"ascii/REAC{Q2010.table_file_stem_suffix}.txt"
        chunks = list(iter_table_chunks(zip_path, member, LEGACY_AERS_TABLES["reac"]))
        frame = pl.concat([c.frame for c in chunks])
        assert frame.height == 2
        assert sum(len(c.quarantined) for c in chunks) == 0
        assert frame.get_column("pt").to_list() == ["Nausea", "Rash"]

    def test_extra_nonempty_field_still_quarantines(self, tmp_path: Path) -> None:
        """The tolerance is exactly one TRAILING EMPTY field, nothing more."""
        from faers_signal_pipeline.ingest.reader import iter_table_chunks
        from faers_signal_pipeline.layout import LEGACY_AERS_TABLES

        zip_path = build_quarter_zip(
            tmp_path / "faers_ascii_2010q1.zip",
            Q2010,
            header_overrides=RAW_HEADERS,
            data_rows={"reac": ["5001$Nausea$EXTRA$"]},
            include_deleted=False,
            subdir="ascii",
            doc_names=("Asc_nts.doc",),
        )
        member = f"ascii/REAC{Q2010.table_file_stem_suffix}.txt"
        chunks = list(iter_table_chunks(zip_path, member, LEGACY_AERS_TABLES["reac"]))
        assert sum(len(c.quarantined) for c in chunks) == 1
        assert sum(c.frame.height for c in chunks) == 0

    def test_modern_era_unaffected_by_trailing_rule(self, tmp_path: Path) -> None:
        """A trailing empty field in a MODERN file is still a mismatch."""
        from tests.factories import row_line

        from faers_signal_pipeline.ingest.reader import iter_table_chunks
        from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES

        quarter = Quarter(2026, 2)
        zip_path = build_quarter_zip(
            tmp_path / "faers_ascii_2026q2.zip",
            quarter,
            data_rows={"reac": [row_line("reac", primaryid="1", caseid="1", pt="Nausea") + "$"]},
        )
        member = f"ASCII/REAC{quarter.table_file_stem_suffix}.txt"
        chunks = list(iter_table_chunks(zip_path, member, FAERS_2014Q3_TABLES["reac"]))
        assert sum(len(c.quarantined) for c in chunks) == 1


class TestVerification:
    def test_real_shaped_legacy_zip_verifies(self, tmp_path: Path) -> None:
        from faers_signal_pipeline.fetch import verify_layout

        report = verify_layout(legacy_zip(tmp_path / "faers_ascii_2010q1.zip"), Q2010)
        assert report.ok, [f.detail for f in report.findings if f.severity == "error"]

    def test_uppercase_txt_members_match(self, tmp_path: Path) -> None:
        """Real legacy members are DEMO10Q1.TXT etc. — matching must hold."""
        from faers_signal_pipeline.fetch import verify_layout

        zip_path = tmp_path / "faers_ascii_2010q1.zip"
        suffix = Q2010.table_file_stem_suffix
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("ascii/Asc_nts.doc", b"doc")
            for table, header in RAW_HEADERS.items():
                archive.writestr(
                    f"ascii/{table.upper()}{suffix}.TXT",
                    (header + "\r\n").encode("latin-1"),
                )
            archive.writestr(f"ascii/STAT{suffix}.TXT", b" \r\n")
        report = verify_layout(zip_path, Q2010)
        assert report.ok, [f.detail for f in report.findings if f.severity == "error"]


class TestResolveEraOrdering:
    def sighting(
        self, caseid: str, caseversion: str | None, quarter: str, primaryid: str
    ) -> dict[str, str | None]:
        return {
            "caseid": caseid,
            "caseversion": caseversion,
            "quarter": quarter,
            "primaryid": primaryid,
        }

    def test_modern_sighting_beats_any_legacy_version(self) -> None:
        from faers_signal_pipeline.dedup.resolve import resolve_current

        rows = [
            self.sighting("800", "9", "2010q1", "5001"),
            self.sighting("800", "1", "2026q2", "9001"),
        ]
        deletions = pl.DataFrame(schema={"caseid": pl.String, "quarter": pl.String})
        for perm in itertools.permutations(rows):
            resolution = resolve_current(pl.DataFrame(list(perm)), deletions)
            row = resolution.current.row(0)
            assert row == ("800", "1", "2026q2", "9001"), row

    def test_blank_legacy_version_resolves_as_zero(self) -> None:
        from faers_signal_pipeline.dedup.resolve import resolve_current

        rows = [
            self.sighting("801", None, "2010q1", "5002"),
            self.sighting("801", "1", "2011q1", "6002"),
        ]
        deletions = pl.DataFrame(schema={"caseid": pl.String, "quarter": pl.String})
        resolution = resolve_current(pl.DataFrame(rows), deletions)
        assert resolution.current.row(0)[1] == "1"  # populated follow-up wins
        assert resolution.stats["superseded_sightings"] == 1

    def test_blank_vs_blank_latest_quarter_wins(self) -> None:
        from faers_signal_pipeline.dedup.resolve import resolve_current

        rows = [
            self.sighting("802", None, "2009q3", "4001"),
            self.sighting("802", None, "2010q2", "5501"),
        ]
        deletions = pl.DataFrame(schema={"caseid": pl.String, "quarter": pl.String})
        resolution = resolve_current(pl.DataFrame(rows), deletions)
        assert resolution.current.row(0)[2] == "2010q2"


@pytestmark_db
class TestLegacyDatabase:
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

    def test_legacy_quarter_loads_raw_fidelity(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        from faers_signal_pipeline.pipeline import load_quarter

        result = load_quarter(
            conn,
            legacy_zip(tmp_path / "q.zip"),
            Q2010,
            report_dir=tmp_path / "r",
            allow_missing_deleted=True,
        )
        assert result.ok
        assert self.scalar(conn, "SELECT count(*) FROM stg_demo") == 2
        # Raw fidelity: staging keeps the blank FOLL_SEQ as NULL...
        assert self.scalar(conn, "SELECT count(*) FROM stg_demo WHERE caseversion IS NULL") == 2
        # ...and carries the legacy-only columns.
        assert self.scalar(conn, "SELECT count(*) FROM stg_demo WHERE image IS NOT NULL") == 2
        assert self.scalar(conn, "SELECT count(*) FROM stg_demo WHERE confid = 'Y'") == 2
        # Children have no caseid in this era; primaryid (ISR) joins them.
        assert self.scalar(conn, "SELECT count(*) FROM stg_drug WHERE caseid IS NULL") == 2
        assert (
            self.scalar(
                conn,
                "SELECT count(*) FROM quarantine WHERE quarter = '2010q1' AND scope = 'row'",
            )
            == 0
        )

    def test_adopting_preexisting_narrow_staging_tables(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """A database whose stg_demo predates the legacy columns (the
        real 2026-08-17 failure) must be adopted by ALTER, not broken."""
        from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES
        from faers_signal_pipeline.pipeline import load_quarter

        columns = ",\n".join(f"{name} text" for name in FAERS_2014Q3_TABLES["demo"].columns)
        conn.execute(f"CREATE TABLE stg_demo (quarter text NOT NULL,\n{columns})")
        result = load_quarter(
            conn,
            legacy_zip(tmp_path / "q.zip"),
            Q2010,
            report_dir=tmp_path / "r",
            allow_missing_deleted=True,
        )
        assert result.ok
        assert self.scalar(conn, "SELECT count(*) FROM stg_demo WHERE image IS NOT NULL") == 2

    def test_three_era_merge(self, conn: psycopg.Connection, tmp_path: Path) -> None:
        """caseid 800: legacy blank@2010q1, era v1@2013q1, modern v2@2026q2
        -> modern wins; caseid 801 legacy-only -> current at version '0'."""
        from tests.factories import row_line
        from tests.test_era_2012q4 import era_zip_2013q1

        from faers_signal_pipeline.db.cases import merge_cases
        from faers_signal_pipeline.pipeline import load_quarter

        load_quarter(
            conn,
            legacy_zip(tmp_path / "a.zip"),
            Q2010,
            report_dir=tmp_path / "r",
            allow_missing_deleted=True,
        )
        load_quarter(
            conn,
            era_zip_2013q1(tmp_path / "b.zip"),
            Quarter(2013, 1),
            report_dir=tmp_path / "r",
            allow_missing_deleted=True,
        )
        modern = build_quarter_zip(
            tmp_path / "c.zip",
            Quarter(2026, 2),
            data_rows={
                "demo": [row_line("demo", primaryid="9002", caseid="800", caseversion="2")],
                "drug": [row_line("drug", primaryid="9002", caseid="800")],
                "reac": [row_line("reac", primaryid="9002", caseid="800", pt="Nausea")],
            },
        )
        load_quarter(conn, modern, Quarter(2026, 2), report_dir=tmp_path / "r")
        resolution, _ = merge_cases(conn, report_dir=tmp_path / "r")
        # 2013q1 fixture contributes caseids 700 and 701; legacy adds 800, 801.
        assert resolution.stats["current_cases"] == 4
        row = conn.execute(
            "SELECT caseversion, quarter FROM current_cases WHERE caseid = '800'"
        ).fetchone()
        assert row == ("2", "2026q2")
        row = conn.execute(
            "SELECT caseversion, quarter FROM current_cases WHERE caseid = '801'"
        ).fetchone()
        assert row == ("0", "2010q1")  # derived version label for blank FOLL_SEQ
        assert (
            self.scalar(
                conn,
                "SELECT count(*) FROM case_versions WHERE caseid = '801' AND version_int = 0",
            )
            == 1
        )


class TestCertifyLegacy:
    def test_legacy_demo_with_null_caseversion_certifies(self) -> None:
        from faers_signal_pipeline.contracts.certify import certify
        from faers_signal_pipeline.layout import LEGACY_AERS_TABLES

        columns = LEGACY_AERS_TABLES["demo"].columns
        frame = pl.DataFrame(
            [{name: {"primaryid": "5001", "caseid": "800"}.get(name) for name in columns}],
            schema=dict.fromkeys(columns, pl.String),
        )
        certified = certify("demo", frame, Era.LEGACY_AERS)
        assert certified.height == 1
