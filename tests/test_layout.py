"""Layout spec invariants."""

from __future__ import annotations

import pytest

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


@pytest.mark.parametrize("era", [Era.LEGACY_AERS, Era.FAERS_2012Q4])
def test_earlier_eras_fail_loudly_until_specified(era: Era) -> None:
    with pytest.raises(NotImplementedError):
        tables_for_era(era)
