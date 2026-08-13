"""Quarter identifiers and FAERS download-artifact naming.

FDA's own file naming is inconsistent across quarters (observed on the QDE
page: ``faers_ascii_2025Q4.zip`` capital Q beside ``faers_ascii_2026q1.zip``
lowercase), so candidate URLs are generated in both casings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from faers_signal_pipeline.layout import Era, era_for_quarter

_QUARTER_RE = re.compile(r"^(?P<year>\d{4})[qQ](?P<quarter>[1-4])$")

#: First quarter published in the FAERS (post-legacy) extract series.
_MIN_YEAR = 2004


class QuarterFormatError(ValueError):
    """A quarter string does not look like ``YYYYqN``."""


@dataclass(frozen=True, slots=True, order=True)
class Quarter:
    """One FAERS publication quarter, e.g. ``Quarter(2026, 2)``."""

    year: int
    quarter: int

    def __post_init__(self) -> None:
        if not 1 <= self.quarter <= 4:
            msg = f"quarter must be 1-4, got {self.quarter}"
            raise QuarterFormatError(msg)
        if self.year < _MIN_YEAR:
            msg = f"year must be >= {_MIN_YEAR}, got {self.year}"
            raise QuarterFormatError(msg)

    @classmethod
    def parse(cls, text: str) -> Quarter:
        """Parse ``2026q2`` / ``2026Q2`` into a Quarter."""
        match = _QUARTER_RE.match(text.strip())
        if match is None:
            msg = f"expected a quarter like '2026q2', got {text!r}"
            raise QuarterFormatError(msg)
        return cls(year=int(match["year"]), quarter=int(match["quarter"]))

    @property
    def label(self) -> str:
        """Canonical lowercase label, e.g. ``2026q2``."""
        return f"{self.year}q{self.quarter}"

    @property
    def era(self) -> Era:
        return era_for_quarter(self.year, self.quarter)

    @property
    def table_file_stem_suffix(self) -> str:
        """Suffix used by table files inside the zip, e.g. ``26Q2``."""
        return f"{self.year % 100:02d}Q{self.quarter}"

    @property
    def deleted_file_name(self) -> str:
        """Deleted-cases list file name inside the zip, e.g. ``DELETE26Q2.txt``.

        Verified against the real 2026q2 archive (``Deleted/DELETE26Q2.txt``):
        a headerless list of CASEIDs, one per line, first line possibly blank.
        """
        return f"DELETE{self.table_file_stem_suffix}.txt"

    def zip_url_candidates(self, base_url: str) -> tuple[str, ...]:
        """Candidate download URLs, most likely casing first."""
        base = base_url.rstrip("/")
        return (
            f"{base}/faers_ascii_{self.year}q{self.quarter}.zip",
            f"{base}/faers_ascii_{self.year}Q{self.quarter}.zip",
        )
