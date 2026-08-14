"""The Phase 4 synthetic mini-corpus — hand-countable by design.

20 cases, 3 mappable synthetic drugs, 1 unmappable name, 4 reactions.
All content is invented. The corpus is small enough that every 2x2 cell in
the maintainer's golden worksheet can be verified by counting this table.

Design targets (each verified by the always-on e2e test):
- ALPHADRUG x Nausea: a=7 — the strong pair.
- BETADRUG x Nausea: a=4 — the near-null pair.
- GAMMADRUG x Rash: a=3 — exactly at the a>=3 threshold.
- ALPHADRUG x Headache: a=2 — must be EXCLUDED by the threshold.
- Case 1019 carries an unmappable drug name: its reaction still counts in
  reaction margins, but it contributes no drug pair (documented exclusion).
- Case 1020 duplicates its drug and reaction rows in-file: counts ONCE
  (case-level counting policy).
- Case 1017 is a multi-drug case (ALPHADRUG + BETADRUG).
"""

from __future__ import annotations

#: caseid -> (drugs, reactions). Order defines file order; content is data.
CASES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "1001": (("ALPHADRUG",), ("Nausea",)),
    "1002": (("ALPHADRUG",), ("Nausea",)),
    "1003": (("ALPHADRUG",), ("Nausea", "Headache")),
    "1004": (("ALPHADRUG",), ("Nausea", "Rash")),
    "1005": (("ALPHADRUG",), ("Nausea",)),
    "1006": (("ALPHADRUG",), ("Headache",)),
    "1007": (("ALPHADRUG",), ("Dizziness",)),
    "1008": (("BETADRUG",), ("Nausea",)),
    "1009": (("BETADRUG",), ("Nausea",)),
    "1010": (("BETADRUG",), ("Nausea",)),
    "1011": (("BETADRUG",), ("Headache",)),
    "1012": (("BETADRUG",), ("Rash",)),
    "1013": (("GAMMADRUG",), ("Rash",)),
    "1014": (("GAMMADRUG",), ("Rash",)),
    "1015": (("GAMMADRUG",), ("Rash",)),
    "1016": (("GAMMADRUG",), ("Dizziness",)),
    "1017": (("ALPHADRUG", "BETADRUG"), ("Nausea", "Dizziness")),
    "1018": (("GAMMADRUG",), ("Headache",)),
    "1019": (("UNMAPPABLE TONIC",), ("Nausea",)),
    "1020": (("ALPHADRUG", "ALPHADRUG"), ("Nausea", "Nausea")),  # in-case dupes
}

#: Synthetic RXCUIs (clearly fake) served by the corpus fake-RxNav client.
CORPUS_RXCUIS: dict[str, str] = {
    "ALPHADRUG": "900001",
    "BETADRUG": "900002",
    "GAMMADRUG": "900003",
}

#: Hand-countable expected cells for qualifying pairs (a >= 3). These are
#: COUNTS (data aggregation), verified by the always-on e2e test; the
#: STATISTICS derived from them are the maintainer's hand-computed goldens.
EXPECTED_CELLS: dict[tuple[str, str], tuple[int, int, int, int]] = {
    # (rxcui, pt): (a, b, c, d) with N = 20
    ("900001", "Nausea"): (7, 2, 4, 7),
    ("900002", "Nausea"): (4, 2, 7, 7),
    ("900003", "Rash"): (3, 2, 2, 13),
}

TOTAL_CASES = len(CASES)
