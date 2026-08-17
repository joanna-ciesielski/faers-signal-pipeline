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

    LEGACY_AERS_EARLY = "legacy_aers_early"
    LEGACY_AERS = "legacy_aers"
    FAERS_2012Q4 = "faers_2012q4"
    FAERS_2014Q3 = "faers_2014q3"

    @property
    def is_legacy(self) -> bool:
        """ISR-keyed AERS eras (everything before the 2012Q4 transition)."""
        return self in (Era.LEGACY_AERS_EARLY, Era.LEGACY_AERS)


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Expected shape of one $-delimited table file within a quarter."""

    name: str
    columns: tuple[str, ...]
    # Column names accepted as aliases at verification time (old -> canonical),
    # e.g. gndr_cod -> sex within the 2014Q3 era.
    aliases: dict[str, str]
    # Every data line of the legacy AERS era ends with a trailing "$"
    # (measured on all 135,784 DEMO rows of the real 2010Q1 archive,
    # 2026-08-17): the reader drops exactly one trailing EMPTY field when
    # this is set. Anything else still quarantines as a field-count
    # mismatch.
    trailing_delimiter: bool = False
    # Columns whose blank is a DOCUMENTED meaning rather than a missing
    # value (legacy FOLL_SEQ blank == initial report == version 0, see
    # docs/dedup-policy.md): the missing_required contract check is
    # skipped for these; staging keeps the raw NULL.
    blank_ok: frozenset[str] = frozenset()


def _spec(
    name: str,
    columns: tuple[str, ...],
    aliases: dict[str, str] | None = None,
    trailing_delimiter: bool = False,
    blank_ok: frozenset[str] = frozenset(),
) -> TableSpec:
    return TableSpec(
        name=name,
        columns=columns,
        aliases=aliases or {},
        trailing_delimiter=trailing_delimiter,
        blank_ok=blank_ok,
    )


#: A UTF-8 byte-order mark as it appears after latin-1 decoding. The real
#: 2012Q4 archive's DRUG file opens with a BOM (observed 2026-08-16); the
#: pipeline reads FAERS bytes as latin-1, so the BOM surfaces as this
#: three-character prefix on the first header column.
_BOM_AS_LATIN1 = "\u00ef\u00bb\u00bf"


def normalize_header(raw_header: str, spec: TableSpec) -> tuple[str, ...]:
    """Lowercase, trim, alias-map, and BOM-strip a raw $-delimited header."""
    raw_header = raw_header.lstrip("\ufeff")
    if raw_header.startswith(_BOM_AS_LATIN1):
        raw_header = raw_header[len(_BOM_AS_LATIN1) :]
    columns = [column.strip().lower() for column in raw_header.rstrip("\r\n").split(DELIMITER)]
    return tuple(spec.aliases.get(column, column) for column in columns)


#: Legacy AERS era (2004 Q1 - 2012 Q3): ISR-keyed identity. Transcribed
#: from the real ``aers_ascii_2010q1.zip`` headers (inspected 2026-08-17).
#: Identity mapping (maintainer-approved policy, docs/dedup-policy.md):
#: ISR -> primaryid (the child-join key), CASE -> caseid,
#: FOLL_SEQ -> caseversion with blank == initial report == version 0.
#: Children carry ISR only (no caseid). Archives use uppercase ``.TXT``
#: members, ship ``Asc_nts.doc``, extra STAT/SIZE members (ignored), no
#: deleted-cases lists, and EVERY data line ends with a trailing ``$``.
LEGACY_AERS_TABLES: dict[str, TableSpec] = {
    "demo": _spec(
        "demo",
        (
            "primaryid",
            "caseid",
            "i_f_code",
            "caseversion",
            "image",
            "event_dt",
            "mfr_dt",
            "fda_dt",
            "rept_cod",
            "mfr_num",
            "mfr_sndr",
            "age",
            "age_cod",
            "sex",
            "e_sub",
            "wt",
            "wt_cod",
            "rept_dt",
            "occp_cod",
            "death_dt",
            "to_mfr",
            "confid",
            "reporter_country",
        ),
        aliases={
            "isr": "primaryid",
            "case": "caseid",
            "i_f_cod": "i_f_code",
            "foll_seq": "caseversion",
            "gndr_cod": "sex",
        },
        trailing_delimiter=True,
        blank_ok=frozenset({"caseversion"}),
    ),
    "drug": _spec(
        "drug",
        (
            "primaryid",
            "drug_seq",
            "role_cod",
            "drugname",
            "val_vbm",
            "route",
            "dose_vbm",
            "dechal",
            "rechal",
            "lot_num",
            "exp_dt",
            "nda_num",
        ),
        aliases={"isr": "primaryid"},
        trailing_delimiter=True,
    ),
    "reac": _spec(
        "reac",
        ("primaryid", "pt"),
        aliases={"isr": "primaryid"},
        trailing_delimiter=True,
    ),
    "outc": _spec(
        "outc",
        ("primaryid", "outc_cod"),
        aliases={"isr": "primaryid"},
        trailing_delimiter=True,
    ),
    "rpsr": _spec(
        "rpsr",
        ("primaryid", "rpsr_cod"),
        aliases={"isr": "primaryid"},
        trailing_delimiter=True,
    ),
    "ther": _spec(
        "ther",
        ("primaryid", "dsg_drug_seq", "start_dt", "end_dt", "dur", "dur_cod"),
        aliases={"isr": "primaryid", "drug_seq": "dsg_drug_seq"},
        trailing_delimiter=True,
    ),
    "indi": _spec(
        "indi",
        ("primaryid", "indi_drug_seq", "indi_pt"),
        aliases={"isr": "primaryid", "drug_seq": "indi_drug_seq"},
        trailing_delimiter=True,
    ),
}

#: Earliest legacy sub-era (2004 Q1 - 2005 Q2): identical to LEGACY_AERS
#: except DEMO ends at CONFID — REPORTER_COUNTRY did not exist yet.
#: Boundary observed on the real archives (2026-08-17 sweep: 2004q1-2005q2
#: fail the 23-column header, 2005q3 onward verify clean). All other
#: tables are shared with LEGACY_AERS.
LEGACY_AERS_EARLY_TABLES: dict[str, TableSpec] = {
    **LEGACY_AERS_TABLES,
    "demo": _spec(
        "demo",
        LEGACY_AERS_TABLES["demo"].columns[:-1],  # ... "confid"
        aliases=LEGACY_AERS_TABLES["demo"].aliases,
        trailing_delimiter=True,
        blank_ok=frozenset({"caseversion"}),
    ),
}

#: 2012 Q4 - 2014 Q2 era: case/version identity, pre-expansion columns.
#: Transcribed from the real ``faers_ascii_2013q1.zip`` headers (inspected
#: 2026-08-16) and that era's packaged per-table PDFs; every era quarter is
#: still runtime-verified against this spec, so any within-era drift fails
#: loudly rather than loading. Differences from the current era: DEMO lacks
#: ``auth_num``/``lit_ref``/``age_grp`` and publishes ``gndr_cod`` (aliased
#: to ``sex``); DRUG lacks ``prod_ai``; REAC lacks ``drug_rec_act``. Era
#: archives use a lowercase ``ascii/`` dir, ship ``Readme.doc``-style docs,
#: and have NO Deleted/ folder (loads take the recorded
#: ``allow_missing_deleted`` override).
FAERS_2012Q4_TABLES: dict[str, TableSpec] = {
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
            "mfr_num",
            "mfr_sndr",
            "age",
            "age_cod",
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
        # Within-era drift, observed on the real 2012Q4 archive
        # (2026-08-16): DRUG published ``lot_nbr`` (renamed ``lot_num``
        # by 2013Q1) and OUTC published ``outc_code`` (later
        # ``outc_cod``). Aliased, same treatment as gndr_cod -> sex.
        aliases={"lot_nbr": "lot_num"},
    ),
    "reac": _spec("reac", ("primaryid", "caseid", "pt")),
    "outc": _spec(
        "outc",
        ("primaryid", "caseid", "outc_cod"),
        aliases={"outc_code": "outc_cod"},
    ),
    "rpsr": _spec("rpsr", ("primaryid", "caseid", "rpsr_cod")),
    "ther": _spec(
        "ther",
        ("primaryid", "caseid", "dsg_drug_seq", "start_dt", "end_dt", "dur", "dur_cod"),
    ),
    "indi": _spec("indi", ("primaryid", "caseid", "indi_drug_seq", "indi_pt")),
}

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
    if (year, quarter) >= (2005, 3):
        return Era.LEGACY_AERS
    return Era.LEGACY_AERS_EARLY


#: Staging tables are shared across eras, so their DDL must come from the
#: UNION of every specified era's columns (CI-gated subset invariant in
#: tests/test_era_2012q4.py and tests/test_era_legacy.py). The union is
#: the current era plus the legacy-only DEMO columns (image, death_dt,
#: confid — raw fidelity; NULL for modern rows). Era specs still drive
#: verification and COPY column lists.
STAGING_SUPERSET_TABLES: dict[str, TableSpec] = {
    **FAERS_2014Q3_TABLES,
    "demo": _spec(
        "demo",
        (*FAERS_2014Q3_TABLES["demo"].columns, "image", "death_dt", "confid"),
        aliases=FAERS_2014Q3_TABLES["demo"].aliases,
    ),
}


def tables_for_era(era: Era) -> dict[str, TableSpec]:
    """Expected table specs for an era.

    Unspecified eras raise so that a backfill crossing an era boundary
    fails loudly until that era's spec is added from its own published
    documentation and real archives (never guessed).
    """
    if era is Era.FAERS_2014Q3:
        return FAERS_2014Q3_TABLES
    if era is Era.FAERS_2012Q4:
        return FAERS_2012Q4_TABLES
    if era is Era.LEGACY_AERS:
        return LEGACY_AERS_TABLES
    return LEGACY_AERS_EARLY_TABLES
