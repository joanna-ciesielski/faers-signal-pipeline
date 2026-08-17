"""Streaming parser for $-delimited FAERS table files inside a quarterly zip.

Known real-world quirks this parser is built around (each one is a named
test case in ``tests/test_reader.py``):

- **No quoting.** FAERS fields are never quoted, so an embedded ``$`` in a
  text field is indistinguishable from a delimiter. A row whose field count
  disagrees with the era spec is therefore quarantined with the raw line
  preserved — never repaired by guessing which ``$`` was data.
- **Embedded line breaks.** A stray LF inside a field splits one logical
  row into two ragged physical lines; both fragments quarantine as
  field-count mismatches. A stray CR (without LF) stays inside the field —
  lines are split on LF only, then a single trailing CR is stripped.
- **Mixed encodings.** Files are decoded as latin-1, which cannot fail and
  preserves every byte; FAERS quarters are ASCII-mostly with occasional
  8-bit bytes.
- **Blank lines.** Skipped, but counted and reported — not quarantined
  (they carry no record content to preserve) and never silently invisible.
- **Empty-string fields.** FAERS blanks mean "not submitted"; they are
  normalized to null at the frame level so downstream checks treat missing
  as missing rather than as an empty token.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from faers_signal_pipeline.layout import DELIMITER, TableSpec, normalize_header

DEFAULT_CHUNK_ROWS = 100_000


class ReaderError(RuntimeError):
    """Structural failure: the member cannot be parsed at all (file-level)."""


@dataclass(frozen=True, slots=True)
class QuarantinedLine:
    """One physical line that failed to parse, with its reason."""

    member: str
    line_no: int  # 1-based, counting the header as line 1
    reason_code: str
    detail: str
    raw_line: str


@dataclass(frozen=True, slots=True)
class TableChunk:
    """A parsed slice of one table: clean rows plus per-line quarantine."""

    frame: pl.DataFrame
    quarantined: tuple[QuarantinedLine, ...]
    blank_lines: int


def _empty_to_null(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.when(pl.col(name).str.len_chars() == 0).then(None).otherwise(pl.col(name)).alias(name)
        for name in frame.columns
    )


def _build_frame(rows: list[list[str]], spec: TableSpec) -> pl.DataFrame:
    frame = pl.DataFrame(
        rows,
        schema=dict.fromkeys(spec.columns, pl.String),
        orient="row",
    )
    return _empty_to_null(frame)


def iter_table_chunks(
    zip_path: Path,
    member: str,
    spec: TableSpec,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
) -> Iterator[TableChunk]:
    """Stream one table member as chunks of clean rows + quarantined lines.

    Raises ``ReaderError`` (file-level) when the member is structurally
    unusable: unreadable archive, missing member, or a header row that does
    not match the era spec. Row-level problems never raise — they quarantine.
    """
    expected = len(spec.columns)
    try:
        with zipfile.ZipFile(zip_path) as archive, archive.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="latin-1", newline="\n")
            header_line = text.readline()
            if not header_line:
                msg = f"{member}: empty file, no header row"
                raise ReaderError(msg)
            header = normalize_header(header_line, spec)
            if header != spec.columns:
                msg = (
                    f"{member}: header mismatch, expected {list(spec.columns)}, "
                    f"found {list(header)}"
                )
                raise ReaderError(msg)

            rows: list[list[str]] = []
            quarantined: list[QuarantinedLine] = []
            blank_lines = 0
            line_no = 1  # header consumed
            for line in text:
                line_no += 1
                stripped = line.rstrip("\n")
                if stripped.endswith("\r"):
                    stripped = stripped[:-1]
                if not stripped.strip():
                    blank_lines += 1
                    continue
                fields = stripped.split(DELIMITER)
                if spec.trailing_delimiter and len(fields) == expected + 1 and fields[-1] == "":
                    # Legacy AERS lines end with a trailing "$" (uniform on
                    # real data); drop exactly the one empty field it makes.
                    fields = fields[:-1]
                if len(fields) != expected:
                    quarantined.append(
                        QuarantinedLine(
                            member=member,
                            line_no=line_no,
                            reason_code="field_count_mismatch",
                            detail=f"expected {expected} fields, found {len(fields)}",
                            raw_line=stripped,
                        )
                    )
                    continue
                rows.append(fields)
                if len(rows) >= chunk_rows:
                    yield TableChunk(
                        frame=_build_frame(rows, spec),
                        quarantined=tuple(quarantined),
                        blank_lines=blank_lines,
                    )
                    rows, quarantined, blank_lines = [], [], 0

            yield TableChunk(
                frame=_build_frame(rows, spec),
                quarantined=tuple(quarantined),
                blank_lines=blank_lines,
            )
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        msg = f"{member}: cannot read from {zip_path.name}: {exc}"
        raise ReaderError(msg) from exc
