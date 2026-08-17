"""Frame-level contract checks on parsed FAERS tables (Polars expressions).

Each check is (reason_code, violation predicate). A row violating any check
routes to quarantine carrying *every* reason it violated (semicolon-joined),
so the DQ report shows the full failure picture, not just the first hit.

Design note (recorded per the Phase 1 plan audit): quarantine *routing*
uses plain Polars expressions because row-level reason attribution needs
per-check control; pandera certifies the surviving frame afterwards
(``certify.py``). Both tools do the job they're best at.

Field semantics and vocabularies cite the ASC_NTS data dictionary.
FAERS dates are partial-precision: ``YYYY``, ``YYYYMM``, or ``YYYYMMDD``,
delivered as submitted (no padding) — validated accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from faers_signal_pipeline.contracts import vocab
from faers_signal_pipeline.layout import TableSpec

REASON_SEPARATOR = ";"


def _is_digits(name: str) -> pl.Expr:
    return pl.col(name).str.contains(r"^\d+$")


def _is_numeric(name: str) -> pl.Expr:
    return pl.col(name).str.contains(r"^\d+(\.\d+)?$")


def _is_partial_date(name: str) -> pl.Expr:
    """FAERS partial date: YYYY, YYYYMM, or YYYYMMDD with sane month/day."""
    col = pl.col(name)
    digits_ok = col.str.contains(r"^(\d{4}|\d{6}|\d{8})$")
    month = col.str.slice(4, 2)
    day = col.str.slice(6, 2)
    month_ok = (col.str.len_chars() < 6) | month.is_between(pl.lit("01"), pl.lit("12"))
    day_ok = (col.str.len_chars() < 8) | day.is_between(pl.lit("01"), pl.lit("31"))
    return digits_ok & month_ok & day_ok


def _required(name: str) -> tuple[str, pl.Expr]:
    return (f"missing_required:{name}", pl.col(name).is_null())


def _digits(name: str) -> tuple[str, pl.Expr]:
    return (f"not_digits:{name}", pl.col(name).is_not_null() & ~_is_digits(name))


def _numeric(name: str) -> tuple[str, pl.Expr]:
    return (f"not_numeric:{name}", pl.col(name).is_not_null() & ~_is_numeric(name))


def _date(name: str) -> tuple[str, pl.Expr]:
    return (f"invalid_date:{name}", pl.col(name).is_not_null() & ~_is_partial_date(name))


def _vocab(name: str, allowed: frozenset[str]) -> tuple[str, pl.Expr]:
    return (
        f"vocab_violation:{name}",
        pl.col(name).is_not_null() & ~pl.col(name).is_in(sorted(allowed)),
    )


_IDS: list[tuple[str, pl.Expr]] = [
    _required("primaryid"),
    _digits("primaryid"),
    _required("caseid"),
    _digits("caseid"),
]

TABLE_CHECKS: dict[str, list[tuple[str, pl.Expr]]] = {
    "demo": [
        *_IDS,
        _required("caseversion"),
        _digits("caseversion"),
        _vocab("i_f_code", vocab.I_F_CODE),
        _date("event_dt"),
        _date("mfr_dt"),
        _date("init_fda_dt"),
        _date("fda_dt"),
        _date("rept_dt"),
        _vocab("rept_cod", vocab.REPT_COD),
        _numeric("age"),
        _vocab("age_cod", vocab.AGE_COD),
        _vocab("age_grp", vocab.AGE_GRP),
        _vocab("sex", vocab.SEX),
        _vocab("e_sub", vocab.E_SUB),
        _numeric("wt"),
        _vocab("wt_cod", vocab.WT_COD),
        _vocab("occp_cod", vocab.OCCP_COD),
    ],
    "drug": [
        *_IDS,
        _required("drug_seq"),
        _digits("drug_seq"),
        _required("role_cod"),
        _vocab("role_cod", vocab.ROLE_COD),
        _required("drugname"),
        _vocab("val_vbm", vocab.VAL_VBM),
        _vocab("dechal", vocab.DECHAL_RECHAL),
        _vocab("rechal", vocab.DECHAL_RECHAL),
        _date("exp_dt"),
        _numeric("dose_amt"),
    ],
    "reac": [*_IDS, _required("pt")],
    "outc": [*_IDS, _required("outc_cod"), _vocab("outc_cod", vocab.OUTC_COD)],
    "rpsr": [*_IDS, _required("rpsr_cod"), _vocab("rpsr_cod", vocab.RPSR_COD)],
    "ther": [
        *_IDS,
        _required("dsg_drug_seq"),
        _digits("dsg_drug_seq"),
        _date("start_dt"),
        _date("end_dt"),
        _numeric("dur"),
        _vocab("dur_cod", vocab.DUR_COD),
    ],
    "indi": [*_IDS, _required("indi_drug_seq"), _digits("indi_drug_seq"), _required("indi_pt")],
}

_REASONS_COLUMN = "__reasons"


@dataclass(frozen=True, slots=True)
class ContractResult:
    """Split of one chunk: rows that passed vs rows quarantined with reasons."""

    good: pl.DataFrame
    quarantined: pl.DataFrame  # original columns + ``reasons`` (joined codes)


def apply_contracts(
    table: str, frame: pl.DataFrame, spec: TableSpec | None = None
) -> ContractResult:
    """Route each row to good/quarantined per the table's contract checks.

    Checks referencing columns the frame's ERA does not publish (e.g.
    ``age_grp`` before 2014Q3) are skipped: a contract on an unpublished
    column cannot apply. The frame's columns come from the era spec, so
    this is era awareness without threading era objects through here.
    When a spec declares ``blank_ok`` columns (blank has a documented
    meaning, e.g. legacy FOLL_SEQ blank == version 0), their
    missing_required checks are skipped too; value-shape checks still
    apply to populated values.
    """
    present = set(frame.columns)
    blank_ok_codes = {
        f"missing_required:{column}" for column in (spec.blank_ok if spec else frozenset())
    }
    checks = [
        (code, expr)
        for code, expr in TABLE_CHECKS[table]
        if set(expr.meta.root_names()) <= present and code not in blank_ok_codes
    ]
    reasons = pl.concat_list(
        [pl.when(expr).then(pl.lit(reason_code)).otherwise(None) for reason_code, expr in checks]
    ).list.drop_nulls()
    annotated = frame.with_columns(reasons.list.join(REASON_SEPARATOR).alias(_REASONS_COLUMN))
    good = annotated.filter(pl.col(_REASONS_COLUMN) == "").drop(_REASONS_COLUMN)
    quarantined = annotated.filter(pl.col(_REASONS_COLUMN) != "").rename(
        {_REASONS_COLUMN: "reasons"}
    )
    return ContractResult(good=good, quarantined=quarantined)


@dataclass(frozen=True, slots=True)
class JoinSplit:
    """Split of a child table by referential integrity to DEMO primaryids."""

    good: pl.DataFrame
    orphans: pl.DataFrame


def split_join_orphans(child: pl.DataFrame, demo_primaryids: pl.Series) -> JoinSplit:
    """Separate child rows whose primaryid has no DEMO row this quarter.

    Orphans are quarantined (reason ``join_orphan``), not loaded: a child
    row without its parent is unanchorable, and its parent may itself have
    been quarantined — the DQ report shows both sides.
    """
    mask = pl.col("primaryid").is_in(demo_primaryids.implode())
    good = child.filter(mask)
    orphans = child.filter(~mask).with_columns(pl.lit("join_orphan").alias("reasons"))
    return JoinSplit(good=good, orphans=orphans)
