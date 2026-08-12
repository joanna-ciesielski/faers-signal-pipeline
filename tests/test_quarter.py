"""Quarter parsing, ordering, era mapping, and URL candidate generation."""

from __future__ import annotations

import pytest

from faers_signal_pipeline.layout import Era
from faers_signal_pipeline.quarter import Quarter, QuarterFormatError


class TestParse:
    @pytest.mark.parametrize("text", ["2026q2", "2026Q2", " 2026q2 "])
    def test_accepts_both_casings_and_whitespace(self, text: str) -> None:
        assert Quarter.parse(text) == Quarter(2026, 2)

    @pytest.mark.parametrize("text", ["2026", "26q2", "2026q5", "2026q0", "q2", "2026-Q2", ""])
    def test_rejects_malformed(self, text: str) -> None:
        with pytest.raises(QuarterFormatError):
            Quarter.parse(text)

    def test_rejects_pre_series_years(self) -> None:
        with pytest.raises(QuarterFormatError):
            Quarter(1999, 1)

    def test_rejects_out_of_range_quarter_direct_construction(self) -> None:
        with pytest.raises(QuarterFormatError):
            Quarter(2026, 5)


class TestProperties:
    def test_label_is_canonical_lowercase(self) -> None:
        assert Quarter.parse("2025Q4").label == "2025q4"

    def test_ordering_is_chronological(self) -> None:
        assert Quarter(2025, 4) < Quarter(2026, 1) < Quarter(2026, 2)

    def test_table_file_stem_suffix(self) -> None:
        assert Quarter(2026, 2).table_file_stem_suffix == "26Q2"
        assert Quarter(2004, 1).table_file_stem_suffix == "04Q1"


class TestEraMapping:
    @pytest.mark.parametrize(
        ("year", "quarter", "era"),
        [
            (2026, 2, Era.FAERS_2014Q3),
            (2014, 3, Era.FAERS_2014Q3),
            (2014, 2, Era.FAERS_2012Q4),
            (2012, 4, Era.FAERS_2012Q4),
            (2012, 3, Era.LEGACY_AERS),
            (2004, 1, Era.LEGACY_AERS),
        ],
    )
    def test_boundaries(self, year: int, quarter: int, era: Era) -> None:
        assert Quarter(year, quarter).era is era


class TestUrlCandidates:
    def test_both_casings_lowercase_first(self) -> None:
        urls = Quarter(2026, 2).zip_url_candidates("https://example.test/Exports/")
        assert urls == (
            "https://example.test/Exports/faers_ascii_2026q2.zip",
            "https://example.test/Exports/faers_ascii_2026Q2.zip",
        )
