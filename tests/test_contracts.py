"""Contract checks: reason routing, join integrity, certification, row models."""

from __future__ import annotations

import polars as pl
import pytest
from pydantic import ValidationError
from tests.factories import row_fields

from faers_signal_pipeline.contracts.certify import certify
from faers_signal_pipeline.contracts.frames import apply_contracts, split_join_orphans
from faers_signal_pipeline.contracts.rows import ROW_MODELS, DemoRow, OutcRow
from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES


def frame_for(table: str, *rows: list[str]) -> pl.DataFrame:
    spec = FAERS_2014Q3_TABLES[table]
    frame = pl.DataFrame(list(rows), schema=dict.fromkeys(spec.columns, pl.String), orient="row")
    return frame.with_columns(
        pl.when(pl.col(c).str.len_chars() == 0).then(None).otherwise(pl.col(c)).alias(c)
        for c in frame.columns
    )


class TestApplyContracts:
    def test_valid_rows_pass_untouched(self) -> None:
        frame = frame_for("outc", row_fields("outc"), row_fields("outc", outc_cod="DE"))
        result = apply_contracts("outc", frame)
        assert result.good.height == 2
        assert result.quarantined.height == 0

    def test_missing_required_id_quarantines(self) -> None:
        frame = frame_for("outc", row_fields("outc", primaryid=""))
        result = apply_contracts("outc", frame)
        assert result.good.height == 0
        [reasons] = result.quarantined.get_column("reasons").to_list()
        assert "missing_required:primaryid" in reasons

    def test_non_digit_id_quarantines(self) -> None:
        frame = frame_for("outc", row_fields("outc", caseid="12AB34"))
        result = apply_contracts("outc", frame)
        [reasons] = result.quarantined.get_column("reasons").to_list()
        assert "not_digits:caseid" in reasons

    def test_vocab_violation_quarantines(self) -> None:
        frame = frame_for("outc", row_fields("outc", outc_cod="ZZ"))
        result = apply_contracts("outc", frame)
        [reasons] = result.quarantined.get_column("reasons").to_list()
        assert "vocab_violation:outc_cod" in reasons

    @pytest.mark.parametrize(
        ("value", "valid"),
        [
            ("2026", True),
            ("202601", True),
            ("20260115", True),
            ("20261301", False),  # month 13
            ("20260132", False),  # day 32
            ("2026011", False),  # 7 digits
            ("ABCD", False),
        ],
    )
    def test_partial_date_validation(self, value: str, valid: bool) -> None:
        frame = frame_for("demo", row_fields("demo", event_dt=value))
        result = apply_contracts("demo", frame)
        if valid:
            assert result.good.height == 1
        else:
            [reasons] = result.quarantined.get_column("reasons").to_list()
            assert "invalid_date:event_dt" in reasons

    def test_null_optional_fields_are_not_violations(self) -> None:
        frame = frame_for(
            "demo",
            row_fields("demo", event_dt="", sex="", age="", wt="", occp_cod="", i_f_code=""),
        )
        result = apply_contracts("demo", frame)
        assert result.good.height == 1

    def test_multiple_violations_all_reported(self) -> None:
        frame = frame_for("demo", row_fields("demo", sex="X", event_dt="BAD", age="old"))
        result = apply_contracts("demo", frame)
        [reasons] = result.quarantined.get_column("reasons").to_list()
        assert "vocab_violation:sex" in reasons
        assert "invalid_date:event_dt" in reasons
        assert "not_numeric:age" in reasons

    def test_drug_required_fields(self) -> None:
        frame = frame_for("drug", row_fields("drug", drugname="", role_cod=""))
        result = apply_contracts("drug", frame)
        [reasons] = result.quarantined.get_column("reasons").to_list()
        assert "missing_required:drugname" in reasons
        assert "missing_required:role_cod" in reasons


class TestJoinIntegrity:
    def test_orphans_split_with_reason(self) -> None:
        child = frame_for(
            "reac",
            row_fields("reac"),
            row_fields("reac", primaryid="9999999991", caseid="99999999"),
        )
        demo_ids = pl.Series("primaryid", ["1000000011"])
        split = split_join_orphans(child, demo_ids)
        assert split.good.height == 1
        assert split.orphans.height == 1
        assert split.orphans.get_column("reasons").to_list() == ["join_orphan"]


class TestCertify:
    def test_certifies_contract_passing_frame(self) -> None:
        frame = frame_for("outc", row_fields("outc"))
        good = apply_contracts("outc", frame).good
        assert certify("outc", good).height == 1

    def test_raises_on_pipeline_invariant_breach(self) -> None:
        import pandera.errors

        broken = frame_for("outc", row_fields("outc")).with_columns(
            pl.lit(None, dtype=pl.String).alias("outc_cod")
        )
        with pytest.raises(pandera.errors.SchemaError):
            certify("outc", broken)


class TestRowModels:
    def test_all_tables_have_models(self) -> None:
        assert set(ROW_MODELS) == set(FAERS_2014Q3_TABLES)

    def test_valid_row_constructs(self) -> None:
        row = OutcRow(primaryid="1000000011", caseid="10000000", outc_cod="HO")
        assert row.outc_cod == "HO"

    def test_non_digit_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="digits only"):
            OutcRow(primaryid="12AB", caseid="10000000", outc_cod="HO")

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DemoRow(
                primaryid="1000000011",
                caseid="10000000",
                caseversion="1",
                bogus="x",  # type: ignore[call-arg]
            )


def test_drug_role_dn_accepted() -> None:
    # DN (Drug Not Administered) documented in ASC_NTS revision "January
    # 2025 (QDE 2024Q4)"; observed 686 times across real 2026q1+2026q2
    # quarters, which is what drove this deliberate vocabulary extension.
    frame = frame_for("drug", row_fields("drug", role_cod="DN"))
    result = apply_contracts("drug", frame)
    assert result.good.height == 1
    assert result.quarantined.height == 0
