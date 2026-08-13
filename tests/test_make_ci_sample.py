"""Tests for the CI sample cutter (runs against a synthetic cached quarter)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import build_quarter_zip
from tests.factories import row_line

from faers_signal_pipeline.fetch import verify_layout
from faers_signal_pipeline.quarter import Quarter
from make_ci_sample import main

QUARTER = Quarter(2026, 2)


def make_cache(tmp_path: Path, rows: int = 10) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir()
    build_quarter_zip(
        cache / "faers_ascii_2026q2.zip",
        QUARTER,
        data_rows={
            table: [row_line(table) for _ in range(rows)]
            for table in ("demo", "drug", "reac", "outc", "rpsr", "ther", "indi")
        },
        deleted_lines=[" ", "10172236", "10923325"],
    )
    return cache


def test_cuts_verified_sample(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    out_dir = tmp_path / "fixtures"
    exit_code = main(
        ["2026q2", "--cache-dir", str(cache), "--rows", "3", "--out-dir", str(out_dir)]
    )
    assert exit_code == 0
    sample = out_dir / "faers_real_sample_2026q2.zip"
    assert sample.exists()
    report = verify_layout(sample, QUARTER)
    assert report.ok
    assert report.deleted_member is not None


def test_sample_is_smaller_than_source(tmp_path: Path) -> None:
    cache = make_cache(tmp_path, rows=50)
    out_dir = tmp_path / "fixtures"
    assert (
        main(["2026q2", "--cache-dir", str(cache), "--rows", "5", "--out-dir", str(out_dir)]) == 0
    )
    from faers_signal_pipeline.ingest.reader import iter_table_chunks
    from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES

    sample = out_dir / "faers_real_sample_2026q2.zip"
    chunks = list(iter_table_chunks(sample, "ASCII/OUTC26Q2.txt", FAERS_2014Q3_TABLES["outc"]))
    assert sum(c.frame.height for c in chunks) == 5


def test_latin1_bytes_survive_sampling(tmp_path: Path) -> None:
    # Regression: writestr defaults to UTF-8; the cutter must encode latin-1
    # so real 8-bit bytes stay byte-identical through sampling.
    cache = tmp_path / "cache"
    cache.mkdir()
    build_quarter_zip(
        cache / "faers_ascii_2026q2.zip",
        QUARTER,
        data_rows={table: [row_line(table)] for table in ("demo", "drug", "rpsr", "ther", "indi")}
        | {
            "outc": [row_line("outc", outc_cod="Ø")],
            "reac": [row_line("reac", pt="Sjögren syndrome")],
        },
        deleted_lines=[" ", "10172236"],
    )
    out_dir = tmp_path / "fixtures"
    assert main(["2026q2", "--cache-dir", str(cache), "--out-dir", str(out_dir)]) == 0

    from faers_signal_pipeline.ingest.reader import iter_table_chunks
    from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES

    sample = out_dir / "faers_real_sample_2026q2.zip"
    [outc] = iter_table_chunks(sample, "ASCII/OUTC26Q2.txt", FAERS_2014Q3_TABLES["outc"])
    assert outc.frame.get_column("outc_cod").to_list() == ["Ø"]
    [reac] = iter_table_chunks(sample, "ASCII/REAC26Q2.txt", FAERS_2014Q3_TABLES["reac"])
    assert reac.frame.get_column("pt").to_list() == ["Sjögren syndrome"]


def test_field_ending_in_cr_keeps_its_byte_through_sampling(tmp_path: Path) -> None:
    # Regression: only the single line terminator is stripped, never a data
    # byte that happens to be CR at the end of the final field.
    cache = tmp_path / "cache"
    cache.mkdir()
    build_quarter_zip(
        cache / "faers_ascii_2026q2.zip",
        QUARTER,
        data_rows={"outc": [row_line("outc", outc_cod="HO\r")]},
        deleted_lines=[" ", "10172236"],
    )
    out_dir = tmp_path / "fixtures"
    assert main(["2026q2", "--cache-dir", str(cache), "--out-dir", str(out_dir)]) == 0

    from faers_signal_pipeline.ingest.reader import iter_table_chunks
    from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES

    sample = out_dir / "faers_real_sample_2026q2.zip"
    [outc] = iter_table_chunks(sample, "ASCII/OUTC26Q2.txt", FAERS_2014Q3_TABLES["outc"])
    assert outc.frame.get_column("outc_cod").to_list() == ["HO\r"]


def test_bad_quarter_exits_2(tmp_path: Path) -> None:
    assert main(["nope", "--cache-dir", str(tmp_path)]) == 2


def test_missing_source_zip_exits_2(tmp_path: Path) -> None:
    assert main(["2026q2", "--cache-dir", str(tmp_path)]) == 2


def test_unverifiable_source_exits_2(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "faers_ascii_2026q2.zip").write_bytes(b"not a zip")
    assert main(["2026q2", "--cache-dir", str(cache)]) == 2
