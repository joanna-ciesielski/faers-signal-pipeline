"""Typed row models (pydantic v2) for FAERS current-era tables.

These are the canonical typed record contracts: strict about identity
fields, permissive-but-typed elsewhere (values arrive as submitted-strings;
semantic validation lives in ``frames.py`` where it can quarantine in bulk
with reasons). The models are used for single-row work — tests, fixtures,
quarantine introspection — while bulk paths stay columnar.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class _Row(BaseModel):
    """Base row: strict schema, no unknown fields, ids always present."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    primaryid: str
    caseid: str

    @field_validator("primaryid", "caseid")
    @classmethod
    def _digits_only(cls, value: str) -> str:
        if not value.isdigit():
            msg = "must be digits only"
            raise ValueError(msg)
        return value


class DemoRow(_Row):
    caseversion: str
    i_f_code: str | None = None
    event_dt: str | None = None
    mfr_dt: str | None = None
    init_fda_dt: str | None = None
    fda_dt: str | None = None
    rept_cod: str | None = None
    auth_num: str | None = None
    mfr_num: str | None = None
    mfr_sndr: str | None = None
    lit_ref: str | None = None
    age: str | None = None
    age_cod: str | None = None
    age_grp: str | None = None
    sex: str | None = None
    e_sub: str | None = None
    wt: str | None = None
    wt_cod: str | None = None
    rept_dt: str | None = None
    to_mfr: str | None = None
    occp_cod: str | None = None
    reporter_country: str | None = None
    occr_country: str | None = None

    @field_validator("caseversion")
    @classmethod
    def _version_digits(cls, value: str) -> str:
        if not value.isdigit():
            msg = "must be digits only"
            raise ValueError(msg)
        return value


class DrugRow(_Row):
    drug_seq: str
    role_cod: str
    drugname: str
    prod_ai: str | None = None
    val_vbm: str | None = None
    route: str | None = None
    dose_vbm: str | None = None
    cum_dose_chr: str | None = None
    cum_dose_unit: str | None = None
    dechal: str | None = None
    rechal: str | None = None
    lot_num: str | None = None
    exp_dt: str | None = None
    nda_num: str | None = None
    dose_amt: str | None = None
    dose_unit: str | None = None
    dose_form: str | None = None
    dose_freq: str | None = None


class ReacRow(_Row):
    pt: str
    drug_rec_act: str | None = None


class OutcRow(_Row):
    outc_cod: str


class RpsrRow(_Row):
    rpsr_cod: str


class TherRow(_Row):
    dsg_drug_seq: str
    start_dt: str | None = None
    end_dt: str | None = None
    dur: str | None = None
    dur_cod: str | None = None


class IndiRow(_Row):
    indi_drug_seq: str
    indi_pt: str


ROW_MODELS: dict[str, type[_Row]] = {
    "demo": DemoRow,
    "drug": DrugRow,
    "reac": ReacRow,
    "outc": OutcRow,
    "rpsr": RpsrRow,
    "ther": TherRow,
    "indi": IndiRow,
}
