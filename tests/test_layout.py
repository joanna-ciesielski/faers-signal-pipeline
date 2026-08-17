"""Layout spec invariants."""

from __future__ import annotations

from faers_signal_pipeline.layout import (
    FAERS_2014Q3_TABLES,
    Era,
    tables_for_era,
)


def test_current_era_has_all_seven_tables() -> None:
    assert set(FAERS_2014Q3_TABLES) == {"demo", "drug", "reac", "outc", "rpsr", "ther", "indi"}


def test_every_table_starts_with_primaryid_caseid() -> None:
    for spec in FAERS_2014Q3_TABLES.values():
        assert spec.columns[:2] == ("primaryid", "caseid")


def test_documented_field_counts() -> None:
    # Anchored to the documentation-derived current-era layout; a real
    # quarter disagreeing with these means era drift -> update deliberately.
    counts = {name: len(spec.columns) for name, spec in FAERS_2014Q3_TABLES.items()}
    assert counts == {
        "demo": 25,
        "drug": 20,
        "reac": 4,
        "outc": 3,
        "rpsr": 3,
        "ther": 7,
        "indi": 4,
    }


def test_demo_accepts_gndr_cod_alias_for_sex() -> None:
    assert FAERS_2014Q3_TABLES["demo"].aliases == {"gndr_cod": "sex"}


def test_every_era_has_a_spec() -> None:
    """All three eras graduated to real specs (Phase 8a: 2012Q4;
    Phase 8b: legacy AERS). The loud-failure guard lived here until then;
    layout drift within an era is still caught by runtime verification."""
    for era in Era:
        assert tables_for_era(era)
