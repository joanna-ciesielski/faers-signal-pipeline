"""Controlled vocabularies from the FAERS ASC_NTS data dictionary.

These sets are deliberately explicit rather than permissive: a value outside
the documented vocabulary quarantines with ``vocab_violation``. If a real
quarter surfaces a legitimate value missing here, the data-quality report
makes it visible and the set is extended deliberately (with the ASC_NTS
citation) — never silently widened.
"""

from __future__ import annotations

I_F_CODE = frozenset({"I", "F"})
SEX = frozenset({"F", "M", "UNK", "NS"})
REPT_COD = frozenset({"EXP", "PER", "DIR", "5DAY", "30DAY"})
AGE_COD = frozenset({"DEC", "YR", "MON", "WK", "DY", "HR"})
AGE_GRP = frozenset({"N", "I", "C", "T", "A", "E"})
WT_COD = frozenset({"KG", "LBS", "GMS"})
E_SUB = frozenset({"Y", "N"})
OCCP_COD = frozenset({"MD", "PH", "OT", "LW", "CN", "HP", "RN"})
ROLE_COD = frozenset({"PS", "SS", "C", "I"})
DECHAL_RECHAL = frozenset({"Y", "N", "U", "D"})
VAL_VBM = frozenset({"1", "2"})
OUTC_COD = frozenset({"DE", "LT", "HO", "DS", "CA", "RI", "OT"})
RPSR_COD = frozenset({"FGN", "SDY", "LIT", "CSM", "HP", "UF", "CR", "DT", "OTH"})
DUR_COD = frozenset({"YR", "MON", "WK", "DAY", "HR", "MIN", "SEC"})
