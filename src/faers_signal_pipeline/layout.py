"""FAERS quarterly ASCII extract layout specification, keyed by era.

Sources (documentation-derived; verified at runtime against each downloaded
quarter — layouts drift across eras and FDA's own packaging is inconsistent):

- FDA FAERS Quarterly Data Extract page (file inventory, "2014 Q3 and later
  quarters feature additional data fields").
- FAERS QDE README / ASC_NTS data dictionary: $-delimited files named
  ``<TABLE>yyQq.txt``; ``primaryid`` = case id + case version; the latest
  ``caseversion`` per ``caseid`` is the current report.

Era boundaries handled here:

- ``LEGACY_AERS``  (through 2012 Q3): ISR/CASE-identified legacy layout.
  Out of scope for dev quarters; declared so full-history backfill fails
  loudly instead of misparsing.
- ``FAERS_2012Q4`` (2012 Q4 - 2014 Q2): case/version ids, pre-expansion.
- ``FAERS_2014Q3`` (2014 Q3 onward): expanded fields (``auth_num``,
  ``lit_ref``, ``age_grp``, ``prod_ai``, ``drug_rec_act``, ``dose_amt``,
  ``dose_unit``, ``dose_freq``, ``route``). Header ``gndr_cod`` was renamed
  ``sex`` in April 2015; the verifier accepts either for this era and
  normalization maps both to ``sex``.

MedDRA note (licensing boundary, ADR 0004): ``reac.pt`` and ``indi.indi_pt``
are MedDRA Preferred Term strings. They are used only as published strings;
the MedDRA hierarchy is never reconstructed, embedded, or displayed.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

DELIMITER = "$"


class Era(enum.StrEnum):
    """FAERS layout era, by the quarter's position in published boundaries."""

    LEGACY_AERS = "legacy_aers"
    FAERS_2012Q4 = "faers_2012q4"
    FAERS_2014Q3 = "faers_2014q3"


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Expected shape of one $-delimited table file within a quarter."""

    name: str
    columns: tuple[str, ...]
    # Column names accepted as aliases at verification time (old -> canonical),
    # e.g. gndr_cod -> sex within the 2014Q3 era.
    aliases: dict[str, str]


def _spec(name: str, columns: tuple[str, ...], aliases: dict[str, str] | None = None) -> TableSpec:
    return TableSpec(name=name, columns=columns, aliases=aliases or {})


#: Current era (2014 Q3 onward). The seven tables and their exact column order.
FAERS_2014Q3_TABLES: dict[str, TableSpec] = {
    "demo": _spec(
        "demo",
        (
            "primaryid",
            "caseid",
            "caseversion",
            "i_f_code",
            "event_dt",
            "mfr_dt",
            "init_fda_dt",
            "fda_dt",
            "rept_cod",
            "auth_num",
            "mfr_num",
            "mfr_sndr",
            "lit_ref",
            "age",
            "age_cod",
            "age_grp",
            "sex",
            "e_sub",
            "wt",
            "wt_cod",
            "rept_dt",
            "to_mfr",
            "occp_cod",
            "reporter_country",
            "occr_country",
        ),
        aliases={"gndr_cod": "sex"},
    ),
    "drug": _spec(
        "drug",
        (
            "primaryid",
            "caseid",
            "drug_seq",
            "role_cod",
            "drugname",
            "prod_ai",
            "val_vbm",
            "route",
            "dose_vbm",
            "cum_dose_chr",
            "cum_dose_unit",
            "dechal",
            "rechal",
            "lot_num",
            "exp_dt",
            "nda_num",
            "dose_amt",
            "dose_unit",
            "dose_form",
            "dose_freq",
        ),
    ),
    "reac": _spec("reac", ("primaryid", "caseid", "pt", "drug_rec_act")),
    "outc": _spec("outc", ("primaryid", "caseid", "outc_cod")),
    "rpsr": _spec("rpsr", ("primaryid", "caseid", "rpsr_cod")),
    "ther": _spec(
        "ther",
        ("primaryid", "caseid", "dsg_drug_seq", "start_dt", "end_dt", "dur", "dur_cod"),
    ),
    "indi": _spec("indi", ("primaryid", "caseid", "indi_drug_seq", "indi_pt")),
}


def era_for_quarter(year: int, quarter: int) -> Era:
    """Map a (year, quarter) to its layout era."""
    if (year, quarter) >= (2014, 3):
        return Era.FAERS_2014Q3
    if (year, quarter) >= (2012, 4):
        return Era.FAERS_2012Q4
    return Era.LEGACY_AERS


def tables_for_era(era: Era) -> dict[str, TableSpec]:
    """Expected table specs for an era.

    Only the current era is fully specified; earlier eras raise so that a
    backfill crossing an era boundary fails loudly until that era's spec is
    added from its own quarter's ASC_NTS documentation (never guessed).
    """
    if era is Era.FAERS_2014Q3:
        return FAERS_2014Q3_TABLES
    msg = (
        f"Layout spec for era {era.value!r} is not yet defined. "
        "Add it from that era's ASC_NTS documentation before loading."
    )
    raise NotImplementedError(msg)
