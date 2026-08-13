"""Cut a small committable CI sample from a real cached FAERS quarter.

FAERS files are US-government public domain (ADR 0004), so committing small
real excerpts is clean — and CI testing real bytes catches quirks synthetic
fixtures can't. Run on a machine that has fetched the quarter:

    uv run python scripts/make_ci_sample.py 2026q2 --rows 25

Writes tests/fixtures/faers_real_sample_<quarter>.zip containing the first
N data lines of each table (plus header), the head of the deleted list, and
placeholder doc members so layout verification passes.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import zipfile
from pathlib import Path

from faers_signal_pipeline.fetch import verify_layout
from faers_signal_pipeline.quarter import Quarter, QuarterFormatError


def _head_lines(archive: zipfile.ZipFile, member: str, count: int) -> list[str]:
    """First N lines of a member, stripping exactly one CRLF/LF terminator.

    Mirrors the reader's line handling: a field genuinely ending in CR keeps
    that byte — only the single terminator is removed, so the sample stays
    byte-faithful to the real quarter.
    """
    with archive.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="latin-1", newline="\n")
        lines: list[str] = []
        for line in text:
            stripped = line.rstrip("\n")
            if stripped.endswith("\r"):
                stripped = stripped[:-1]
            lines.append(stripped)
            if len(lines) >= count:
                break
        return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quarter", help="cached quarter to sample, e.g. 2026q2")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.environ.get("FAERS_CACHE_DIR", "data/faers-cache")),
    )
    parser.add_argument("--rows", type=int, default=25, help="data rows per table")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("tests/fixtures"), help="output directory"
    )
    args = parser.parse_args(argv)

    try:
        quarter = Quarter.parse(args.quarter)
    except QuarterFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    zip_path = args.cache_dir / f"faers_ascii_{quarter.label}.zip"
    if not zip_path.exists():
        print(f"error: {zip_path} not found", file=sys.stderr)
        return 2
    verification = verify_layout(zip_path, quarter)
    if not verification.ok:
        print("error: source zip fails layout verification", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"faers_real_sample_{quarter.label}.zip"
    with zipfile.ZipFile(zip_path) as source, zipfile.ZipFile(out_path, "w") as target:
        target.writestr("ASCII/ASC_NTS.pdf", b"sample placeholder; see real quarter")
        target.writestr("Readme.pdf", b"sample placeholder; see real quarter")
        # Encode latin-1 explicitly: writestr's default is UTF-8, which would
        # re-encode real 8-bit bytes and break byte-fidelity (the same bug
        # class fixed in the test fixture builder).
        for member in verification.table_members.values():
            lines = _head_lines(source, member, args.rows + 1)  # +1 header
            target.writestr(member, ("\r\n".join(lines) + "\r\n").encode("latin-1"))
        if verification.deleted_member is not None:
            lines = _head_lines(source, verification.deleted_member, args.rows)
            target.writestr(
                verification.deleted_member, ("\n".join(lines) + "\n").encode("latin-1")
            )

    sample_check = verify_layout(out_path, quarter)
    if not sample_check.ok:
        print("error: generated sample fails layout verification", file=sys.stderr)
        return 1
    print(f"wrote {out_path} (verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
