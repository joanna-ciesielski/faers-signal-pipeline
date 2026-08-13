"""Named FAERS quirk tests + property-based tests for the streaming parser.

Every known real-world quirk is a named test; the hypothesis suite then
asserts the global invariant: any line either parses or quarantines with a
reason — never crashes, never disappears.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tests.conftest import build_quarter_zip
from tests.factories import row_line

from faers_signal_pipeline.ingest.reader import ReaderError, TableChunk, iter_table_chunks
from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES
from faers_signal_pipeline.quarter import Quarter

QUARTER = Quarter(2026, 2)
OUTC_SPEC = FAERS_2014Q3_TABLES["outc"]
OUTC_MEMBER = "ASCII/OUTC26Q2.txt"


def parse_outc(tmp_path: Path, lines: list[str], **zip_kwargs: object) -> list[TableChunk]:
    path = build_quarter_zip(
        tmp_path / "q.zip",
        QUARTER,
        data_rows={"outc": lines},
        **zip_kwargs,  # type: ignore[arg-type]
    )
    return list(iter_table_chunks(path, OUTC_MEMBER, OUTC_SPEC))


class TestNamedQuirks:
    def test_clean_rows_parse(self, tmp_path: Path) -> None:
        chunks = parse_outc(tmp_path, [row_line("outc"), row_line("outc", outc_cod="DE")])
        assert sum(c.frame.height for c in chunks) == 2
        assert not any(c.quarantined for c in chunks)

    def test_quirk_field_count_mismatch_quarantines(self, tmp_path: Path) -> None:
        # An embedded $ in a field is indistinguishable from a delimiter:
        # the row must quarantine, never be repaired by guessing.
        bad = row_line("outc", outc_cod="HO") + "$EXTRA"
        [chunk] = parse_outc(tmp_path, [row_line("outc"), bad])
        assert chunk.frame.height == 1
        [q] = chunk.quarantined
        assert q.reason_code == "field_count_mismatch"
        assert "expected 3 fields, found 4" in q.detail
        assert q.raw_line == bad
        assert q.line_no == 3  # header is line 1

    def test_quirk_embedded_lf_splits_into_two_quarantined_fragments(self, tmp_path: Path) -> None:
        # A stray LF inside a middle field splits one logical row into two
        # ragged physical lines; both fragments quarantine.
        broken = row_line("outc", caseid="100\n200")
        [chunk] = parse_outc(tmp_path, [broken])
        assert chunk.frame.height == 0
        assert len(chunk.quarantined) == 2
        assert {q.reason_code for q in chunk.quarantined} == {"field_count_mismatch"}

    def test_quirk_embedded_lf_after_final_field_makes_first_fragment_valid(
        self, tmp_path: Path
    ) -> None:
        # Honest limitation of unquoted data: when the stray LF lands exactly
        # after a complete field set, the first fragment is indistinguishable
        # from a valid row and parses; only the tail fragment quarantines.
        # Contract checks downstream are the safety net for the tail's data.
        broken = row_line("outc", outc_cod="HO\nDS")
        [chunk] = parse_outc(tmp_path, [broken])
        assert chunk.frame.height == 1
        assert chunk.frame.get_column("outc_cod").to_list() == ["HO"]
        [q] = chunk.quarantined
        assert q.reason_code == "field_count_mismatch"
        assert q.raw_line == "DS"

    def test_quirk_embedded_cr_stays_in_field(self, tmp_path: Path) -> None:
        # A bare CR (no LF) is data, not a line break: only the single
        # trailing CR of the CRLF terminator is stripped.
        [chunk] = parse_outc(tmp_path, [row_line("outc", outc_cod="HO\rX")])
        assert chunk.frame.height == 1
        assert chunk.frame.get_column("outc_cod").to_list() == ["HO\rX"]

    def test_quirk_latin1_bytes_survive(self, tmp_path: Path) -> None:
        [chunk] = parse_outc(tmp_path, [row_line("outc", outc_cod="Ø")])
        assert chunk.frame.get_column("outc_cod").to_list() == ["Ø"]

    def test_quirk_blank_lines_counted_not_quarantined(self, tmp_path: Path) -> None:
        [chunk] = parse_outc(tmp_path, [row_line("outc"), "", "   ", row_line("outc")])
        assert chunk.frame.height == 2
        assert chunk.blank_lines == 2
        assert not chunk.quarantined

    def test_quirk_empty_fields_become_null(self, tmp_path: Path) -> None:
        [chunk] = parse_outc(tmp_path, [row_line("outc", outc_cod="")])
        assert chunk.frame.get_column("outc_cod").to_list() == [None]

    def test_quirk_trailing_delimiter_is_field_count_mismatch(self, tmp_path: Path) -> None:
        [chunk] = parse_outc(tmp_path, [row_line("outc") + "$"])
        [q] = chunk.quarantined
        assert q.reason_code == "field_count_mismatch"


class TestStructuralFailures:
    def test_header_mismatch_raises_reader_error(self, tmp_path: Path) -> None:
        path = build_quarter_zip(
            tmp_path / "q.zip",
            QUARTER,
            header_overrides={"outc": "PRIMARYID$CASEID$WRONG"},
        )
        with pytest.raises(ReaderError, match="header mismatch"):
            list(iter_table_chunks(path, OUTC_MEMBER, OUTC_SPEC))

    def test_empty_member_raises_reader_error(self, tmp_path: Path) -> None:
        path = build_quarter_zip(tmp_path / "q.zip", QUARTER)
        import zipfile

        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("ASCII/EMPTY26Q2.txt", "")
        with pytest.raises(ReaderError, match="empty file"):
            list(iter_table_chunks(path, "ASCII/EMPTY26Q2.txt", OUTC_SPEC))

    def test_missing_member_raises_reader_error(self, tmp_path: Path) -> None:
        path = build_quarter_zip(tmp_path / "q.zip", QUARTER)
        with pytest.raises(ReaderError, match="cannot read"):
            list(iter_table_chunks(path, "ASCII/NOPE26Q2.txt", OUTC_SPEC))


class TestChunking:
    def test_rows_split_across_chunks_without_loss(self, tmp_path: Path) -> None:
        lines = [row_line("outc") for _ in range(7)]
        path = build_quarter_zip(tmp_path / "q.zip", QUARTER, data_rows={"outc": lines})
        chunks = list(iter_table_chunks(path, OUTC_MEMBER, OUTC_SPEC, chunk_rows=3))
        assert [c.frame.height for c in chunks] == [3, 3, 1]
        assert sum(c.frame.height for c in chunks) == 7


class TestPropertyBased:
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        lines=st.lists(
            st.text(
                alphabet=st.characters(codec="latin-1", exclude_characters="\n"),
                max_size=120,
            ),
            max_size=20,
        )
    )
    def test_any_line_parses_or_quarantines_never_vanishes(
        self, tmp_path_factory: pytest.TempPathFactory, lines: list[str]
    ) -> None:
        tmp_path = tmp_path_factory.mktemp("hypo")
        path = build_quarter_zip(tmp_path / "q.zip", QUARTER, data_rows={"outc": lines})
        chunks = list(iter_table_chunks(path, OUTC_MEMBER, OUTC_SPEC))
        parsed = sum(c.frame.height for c in chunks)
        quarantined = sum(len(c.quarantined) for c in chunks)
        blank = sum(c.blank_lines for c in chunks)
        # Invariant: every physical line is accounted for exactly once.
        # (CR is stripped only as a line terminator; a line of "\r" alone
        # counts as blank after stripping.)
        assert parsed + quarantined + blank == len(lines)
