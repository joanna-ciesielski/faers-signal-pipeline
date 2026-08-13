"""Builders for valid synthetic FAERS rows (all content invented)."""

from __future__ import annotations

from faers_signal_pipeline.layout import DELIMITER, FAERS_2014Q3_TABLES

_BASE_VALUES: dict[str, dict[str, str]] = {
    "demo": {
        "primaryid": "1000000011",
        "caseid": "10000000",
        "caseversion": "1",
        "i_f_code": "I",
        "event_dt": "20260101",
        "fda_dt": "20260401",
        "rept_cod": "EXP",
        "age": "62",
        "age_cod": "YR",
        "sex": "F",
        "e_sub": "Y",
        "wt": "70.5",
        "wt_cod": "KG",
        "rept_dt": "20260402",
        "occp_cod": "MD",
        "reporter_country": "US",
        "occr_country": "US",
    },
    "drug": {
        "primaryid": "1000000011",
        "caseid": "10000000",
        "drug_seq": "1",
        "role_cod": "PS",
        "drugname": "EXAMPLEDRUG",
        "prod_ai": "EXAMPLINE",
        "route": "ORAL",
        "dose_amt": "10",
        "dose_unit": "MG",
    },
    "reac": {"primaryid": "1000000011", "caseid": "10000000", "pt": "Nausea"},
    "outc": {"primaryid": "1000000011", "caseid": "10000000", "outc_cod": "HO"},
    "rpsr": {"primaryid": "1000000011", "caseid": "10000000", "rpsr_cod": "HP"},
    "ther": {
        "primaryid": "1000000011",
        "caseid": "10000000",
        "dsg_drug_seq": "1",
        "start_dt": "20251215",
        "dur": "30",
        "dur_cod": "DAY",
    },
    "indi": {
        "primaryid": "1000000011",
        "caseid": "10000000",
        "indi_drug_seq": "1",
        "indi_pt": "Hypertension",
    },
}


def row_fields(table: str, **overrides: str) -> list[str]:
    """Ordered field values for one valid row, with named overrides."""
    spec = FAERS_2014Q3_TABLES[table]
    values = dict(_BASE_VALUES[table])
    unknown = set(overrides) - set(spec.columns)
    if unknown:
        msg = f"unknown columns for {table}: {sorted(unknown)}"
        raise KeyError(msg)
    values.update(overrides)
    return [values.get(column, "") for column in spec.columns]


def row_line(table: str, **overrides: str) -> str:
    """One valid $-delimited data line for a table."""
    return DELIMITER.join(row_fields(table, **overrides))
