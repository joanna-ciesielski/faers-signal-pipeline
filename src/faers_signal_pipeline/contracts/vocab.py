"""Controlled vocabularies from the FAERS ASC_NTS data dictionary.

These sets are deliberately explicit rather than permissive: a value outside
the documented vocabulary quarantines with ``vocab_violation``. If a real
quarter surfaces a legitimate value missing here, the data-quality report
makes it visible and the set is extended deliberately (with the ASC_NTS
citation) — never silently widened.
"""

from __future__ import annotations

I_F_CODE = frozenset({"I", "F"})
# ASC_NTS (Jan 2025) documents UNK/M/F. NS is retained for legacy-era
# tolerance; observed 2026q1+2026q2 data contains only F/M/null. Review at
# full-history backfill.
SEX = frozenset({"F", "M", "UNK", "NS"})
REPT_COD = frozenset({"EXP", "PER", "DIR", "5DAY", "30DAY"})
AGE_COD = frozenset({"DEC", "YR", "MON", "WK", "DY", "HR"})
AGE_GRP = frozenset({"N", "I", "C", "T", "A", "E"})
WT_COD = frozenset({"KG", "LBS", "GMS"})
E_SUB = frozenset({"Y", "N"})
# ASC_NTS (Jan 2025) documents MD/PH/OT/LW/CN. HP is OBSERVED in real
# 2026q1+2026q2 data despite being undocumented there (audited 2026-08-13);
# RN retained for legacy-era tolerance, unobserved in dev quarters. Review
# at full-history backfill.
OCCP_COD = frozenset({"MD", "PH", "OT", "LW", "CN", "HP", "RN"})
# DN added by ASC_NTS revision "January 2025 (QDE 2024Q4)": Drug Not
# Administered became a valid ROLE_COD (E2B(R3) harmonization). Observed
# 686 times across real 2026q1+2026q2 before this deliberate extension.
ROLE_COD = frozenset({"PS", "SS", "C", "I", "DN"})
DECHAL_RECHAL = frozenset({"Y", "N", "U", "D"})
VAL_VBM = frozenset({"1", "2"})
OUTC_COD = frozenset({"DE", "LT", "HO", "DS", "CA", "RI", "OT"})
RPSR_COD = frozenset({"FGN", "SDY", "LIT", "CSM", "HP", "UF", "CR", "DT", "OTH"})
DUR_COD = frozenset({"YR", "MON", "WK", "DAY", "HR", "MIN", "SEC"})
