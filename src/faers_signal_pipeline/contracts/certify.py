"""Certification gate: pandera schemas over frames that passed contracts.

This is not a second quarantine path — by the time a frame reaches
certification, every row-level violation has already been routed with a
reason. Certification asserts the *invariants of the pipeline itself*
(columns, dtypes, required non-nulls). A failure here is a programming
error and raises; it never silently discards data.
"""

from __future__ import annotations

import pandera.polars as pa
import polars as pl

from faers_signal_pipeline.layout import Era, tables_for_era

_REQUIRED_NON_NULL: dict[str, frozenset[str]] = {
    "demo": frozenset({"primaryid", "caseid", "caseversion"}),
    "drug": frozenset({"primaryid", "caseid", "drug_seq", "role_cod", "drugname"}),
    "reac": frozenset({"primaryid", "caseid", "pt"}),
    "outc": frozenset({"primaryid", "caseid", "outc_cod"}),
    "rpsr": frozenset({"primaryid", "caseid", "rpsr_cod"}),
    "ther": frozenset({"primaryid", "caseid", "dsg_drug_seq"}),
    "indi": frozenset({"primaryid", "caseid", "indi_drug_seq", "indi_pt"}),
}


def _schema_for(table: str, era: Era) -> pa.DataFrameSchema:
    required = _REQUIRED_NON_NULL[table]
    spec = tables_for_era(era)[table]
    return pa.DataFrameSchema(
        {column: pa.Column(str, nullable=column not in required) for column in spec.columns},
        strict=True,
        ordered=True,
    )


#: Schemas are era-keyed: certification asserts the frame carries exactly
#: its ERA's columns (the required non-null identity columns exist in
#: every specified era). Built lazily so unspecified eras never construct.
_SCHEMAS: dict[tuple[str, Era], pa.DataFrameSchema] = {}


def certify(table: str, frame: pl.DataFrame, era: Era = Era.FAERS_2014Q3) -> pl.DataFrame:
    """Validate a contract-passing frame against its era's pandera schema.

    Returns the validated frame; raises ``pandera.errors.SchemaError`` on an
    invariant breach (which is a bug in the pipeline, not bad input data).
    """
    key = (table, era)
    if key not in _SCHEMAS:
        _SCHEMAS[key] = _schema_for(table, era)
    validated = _SCHEMAS[key].validate(frame)
    assert isinstance(validated, pl.DataFrame)  # noqa: S101 - narrowing for mypy
    return validated
