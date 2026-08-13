"""Deleted-cases list parser tests (format verified on real 2026q2 data)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import build_quarter_zip

from faers_signal_pipeline.ingest.deleted import parse_deleted_list
from faers_signal_pipeline.ingest.reader import ReaderError
from faers_signal_pipeline.quarter import Quarter

QUARTER = Quarter(2026, 2)
MEMBER = "Deleted/DELETE26Q2.txt"


def make_zip(tmp_path: Path, lines: list[str]) -> Path:
    return build_quarter_zip(tmp_path / "q.zip", QUARTER, deleted_lines=lines)


def test_real_format_leading_blank_then_bare_caseids(tmp_path: Path) -> None:
    # Mirrors the observed real file: blank/whitespace first line, then ids.
    path = make_zip(tmp_path, [" ", "10172236", "10923325", "10965864"])
    result = parse_deleted_list(path, MEMBER)
    assert result.caseids == ("10172236", "10923325", "10965864")
    assert result.blank_lines == 1
    assert not result.quarantined


def test_whitespace_around_ids_is_stripped(tmp_path: Path) -> None:
    path = make_zip(tmp_path, ["  10172236  ", "10923325\r"])
    result = parse_deleted_list(path, MEMBER)
    assert result.caseids == ("10172236", "10923325")


def test_non_digit_line_quarantines(tmp_path: Path) -> None:
    path = make_zip(tmp_path, ["10172236", "OOPS-123", "10923325"])
    result = parse_deleted_list(path, MEMBER)
    assert result.caseids == ("10172236", "10923325")
    [q] = result.quarantined
    assert q.reason_code == "invalid_caseid"
    assert q.line_no == 2
    assert q.raw_line == "OOPS-123"


def test_empty_list_is_valid(tmp_path: Path) -> None:
    path = make_zip(tmp_path, [""])
    result = parse_deleted_list(path, MEMBER)
    assert result.caseids == ()


def test_missing_member_raises(tmp_path: Path) -> None:
    path = build_quarter_zip(tmp_path / "q.zip", QUARTER, include_deleted=False)
    with pytest.raises(ReaderError, match="cannot read"):
        parse_deleted_list(path, MEMBER)
