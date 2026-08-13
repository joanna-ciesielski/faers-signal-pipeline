"""Parser for the quarterly deleted-cases list (``Deleted/DELETE{yy}Q{q}.txt``).

Format verified against the real 2026q2 archive: a headerless list of
CASEIDs, one per line, digits only, with a possible leading blank/whitespace
line. Blank lines are skipped and counted; any non-digit line quarantines.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from faers_signal_pipeline.ingest.reader import QuarantinedLine, ReaderError


@dataclass(frozen=True, slots=True)
class DeletedCases:
    """Parsed deleted-cases list for one quarter."""

    caseids: tuple[str, ...]
    quarantined: tuple[QuarantinedLine, ...]
    blank_lines: int


def parse_deleted_list(zip_path: Path, member: str) -> DeletedCases:
    """Parse the deleted-cases member into CASEIDs (+ quarantine for oddities)."""
    caseids: list[str] = []
    quarantined: list[QuarantinedLine] = []
    blank_lines = 0
    try:
        with zipfile.ZipFile(zip_path) as archive, archive.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="latin-1", newline="\n")
            for line_no, line in enumerate(text, start=1):
                token = line.strip()
                if not token:
                    blank_lines += 1
                    continue
                if not token.isdigit():
                    quarantined.append(
                        QuarantinedLine(
                            member=member,
                            line_no=line_no,
                            reason_code="invalid_caseid",
                            detail="expected a digits-only CASEID",
                            raw_line=line.rstrip("\r\n"),
                        )
                    )
                    continue
                caseids.append(token)
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        msg = f"{member}: cannot read from {zip_path.name}: {exc}"
        raise ReaderError(msg) from exc
    return DeletedCases(
        caseids=tuple(caseids),
        quarantined=tuple(quarantined),
        blank_lines=blank_lines,
    )
