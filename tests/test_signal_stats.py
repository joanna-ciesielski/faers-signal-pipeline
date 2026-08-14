"""Statistics function tests: mathematical IDENTITIES and guards only.

These are labeled identities deliberately: they verify algebraic facts any
correct implementation must satisfy (uniform table => PRR=ROR=1, chi2=0;
transposition inverts ROR; CI symmetry in log space). The golden values in
TestGoldens are the authoritative numeric validation; see that class's
docstring for their provenance (rule-6 waiver, manual arithmetic,
independent scipy/statsmodels verification, three-way agreement).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from faers_signal_pipeline.signals.contingency import build_contingency
from faers_signal_pipeline.signals.stats import chi_square, prr, ror

GOLDENS_PATH = Path(__file__).parent / "goldens" / "phase4_goldens.json"


class TestIdentities:
    def test_uniform_table_is_null_signal(self) -> None:
        """a=b=c=d: drug and reaction are independent => PRR=ROR=1, chi2=0."""
        est_prr = prr(5, 5, 5, 5)
        est_ror = ror(5, 5, 5, 5)
        assert est_prr is not None and est_ror is not None
        assert est_prr.value == pytest.approx(1.0)
        assert est_ror.value == pytest.approx(1.0)
        assert chi_square(5, 5, 5, 5) == pytest.approx(0.0)

    def test_transposed_table_inverts_ror(self) -> None:
        """Swapping the drug rows (a<->c, b<->d) inverts the odds ratio."""
        forward = ror(7, 2, 4, 7)
        swapped = ror(4, 7, 7, 2)
        assert forward is not None and swapped is not None
        assert swapped.value == pytest.approx(1.0 / forward.value)

    def test_ci_is_symmetric_in_log_space(self) -> None:
        est = ror(7, 2, 4, 7)
        assert est is not None
        log_low = math.log(est.value) - math.log(est.ci_low)
        log_high = math.log(est.ci_high) - math.log(est.value)
        assert log_low == pytest.approx(log_high)

    def test_chi_square_is_symmetric_under_transposition(self) -> None:
        assert chi_square(7, 2, 4, 7) == pytest.approx(chi_square(4, 7, 7, 2))

    def test_point_estimate_lies_inside_its_ci(self) -> None:
        for cells in [(7, 2, 4, 7), (4, 2, 7, 7), (3, 2, 2, 13)]:
            est_prr = prr(*cells)
            est_ror = ror(*cells)
            assert est_prr is not None and est_ror is not None
            assert est_prr.ci_low < est_prr.value < est_prr.ci_high
            assert est_ror.ci_low < est_ror.value < est_ror.ci_high


class TestZeroGuards:
    def test_zero_a_returns_none(self) -> None:
        assert prr(0, 5, 5, 5) is None
        assert ror(0, 5, 5, 5) is None

    def test_zero_cells_never_fabricate(self) -> None:
        assert ror(5, 0, 5, 5) is None
        assert prr(5, 5, 0, 5) is None

    def test_chi_square_zero_margin_returns_none(self) -> None:
        assert chi_square(0, 0, 5, 5) is None


class TestGoldens:
    """The authoritative numeric validation.

    Provenance (recorded 2026-08-13): standing rule 6 (maintainer
    hand-computes goldens) was explicitly waived by maintainer instruction.
    Values were manually computed step by step, verified against scipy and
    statsmodels (independent implementations), then compared to this
    pipeline — three-way agreement required. Worked arithmetic:

    Pair 1 — ALPHADRUG x Nausea: a=7 b=2 c=4 d=7, N=20
      PRR = (7/9)/(4/11) = 77/36 = 2.138889
      SE(lnPRR) = sqrt(1/7 - 1/9 + 1/4 - 1/11) = sqrt(0.190837) = 0.436848
      lnPRR = 0.760292; CI = exp(0.760292 -/+ 1.95996*0.436848)
            = exp(-0.095916)=0.908535 .. exp(1.616499)=5.035408
      ROR = 49/8 = 6.125
      SE(lnROR) = sqrt(1/7 + 1/2 + 1/4 + 1/7) = sqrt(1.035714) = 1.017700
      lnROR = 1.812379; CI = exp(-0.182276)=0.833370 .. exp(3.807034)=45.016769
      chi2 = 20*(49-8)^2 / (9*11*11*9) = 33620/9801 = 3.430262

    Pair 2 — BETADRUG x Nausea: a=4 b=2 c=7 d=7, N=20
      PRR = (4/6)/(7/14) = 4/3 = 1.333333
      SE = sqrt(1/4 - 1/6 + 1/7 - 1/14) = sqrt(0.154762) = 0.393398
      CI = exp(0.287682 -/+ 0.771046) = 0.616706 .. 2.882701
      ROR = 28/14 = 2.0; SE = sqrt(1/4+1/2+1/7+1/7) = 1.017700
      CI = exp(0.693147 -/+ 1.994655) = 0.272121 .. 14.699353
      chi2 = 20*(28-14)^2 / (6*14*11*9) = 3920/8316 = 0.471380

    Pair 3 — GAMMADRUG x Rash: a=3 b=2 c=2 d=13, N=20
      PRR = (3/5)/(2/15) = 4.5
      SE = sqrt(1/3 - 1/5 + 1/2 - 1/15) = sqrt(0.566667) = 0.752773
      CI = exp(1.504077 -/+ 1.475409) = 1.029085 .. 19.677674
      ROR = 39/4 = 9.75; SE = sqrt(1/3+1/2+1/2+1/13) = sqrt(1.410256) = 1.187542
      CI = exp(2.277267 -/+ 2.327543) = 0.950970 .. 99.963705
      chi2 = 20*(39-4)^2 / (5*15*5*15) = 24500/5625 = 4.355556
    """

    def _load(self) -> dict[str, dict[str, object]]:
        payload = json.loads(GOLDENS_PATH.read_text(encoding="utf-8"))
        pairs: dict[str, dict[str, object]] = payload["pairs"]
        if any(value is None for pair in pairs.values() for value in pair.values()):
            pytest.skip(
                "golden values pending maintainer hand computation"
                " (docs/goldens/phase4-worksheet.md)"
            )
        return pairs

    def test_goldens_match_implementation(self) -> None:
        pairs = self._load()
        for name, golden in pairs.items():
            a, b, c, d = (
                int(str(golden["a"])),
                int(str(golden["b"])),
                int(str(golden["c"])),
                int(str(golden["d"])),
            )
            est_prr = prr(a, b, c, d)
            est_ror = ror(a, b, c, d)
            chi2 = chi_square(a, b, c, d)
            assert est_prr is not None and est_ror is not None and chi2 is not None
            tol = 5e-3  # hand computation carries ~3 significant decimals
            assert est_prr.value == pytest.approx(float(str(golden["prr"])), abs=tol), name
            assert est_prr.ci_low == pytest.approx(float(str(golden["prr_ci_low"])), abs=tol), name
            assert est_prr.ci_high == pytest.approx(float(str(golden["prr_ci_high"])), abs=tol), (
                name
            )
            assert est_ror.value == pytest.approx(float(str(golden["ror"])), abs=tol), name
            assert est_ror.ci_low == pytest.approx(float(str(golden["ror_ci_low"])), abs=tol), name
            assert est_ror.ci_high == pytest.approx(float(str(golden["ror_ci_high"])), abs=tol), (
                name
            )
            assert chi2 == pytest.approx(float(str(golden["chi_square"])), abs=tol), name


class TestContingencyCountingPolicy:
    def test_case_counts_pair_once_despite_duplicates(self) -> None:
        import polars as pl

        drugs = pl.DataFrame(
            [("1", "900001"), ("1", "900001"), ("2", "900001"), ("3", "900001")],
            schema={"caseid": pl.String, "rxcui": pl.String},
            orient="row",
        )
        reactions = pl.DataFrame(
            [("1", "Nausea"), ("1", "Nausea"), ("2", "Nausea"), ("3", "Nausea")],
            schema={"caseid": pl.String, "pt": pl.String},
            orient="row",
        )
        result = build_contingency(drugs, reactions, total_cases=10, min_count=3)
        assert result.pairs.get_column("a").to_list() == [3]

    def test_below_threshold_pairs_excluded_and_counted(self) -> None:
        import polars as pl

        drugs = pl.DataFrame(
            [("1", "900001"), ("2", "900001")],
            schema={"caseid": pl.String, "rxcui": pl.String},
            orient="row",
        )
        reactions = pl.DataFrame(
            [("1", "Nausea"), ("2", "Nausea")],
            schema={"caseid": pl.String, "pt": pl.String},
            orient="row",
        )
        result = build_contingency(drugs, reactions, total_cases=10, min_count=3)
        assert result.pairs.height == 0
        assert result.stats["observed_pairs"] == 1
        assert result.stats["below_threshold_pairs"] == 1


class TestMutationSpotCheck:
    """The goldens have teeth: plausible-but-wrong formula variants must
    FAIL against them (build-plan requirement: break a formula -> a test
    fails). Each mutation here is a real-world mistake someone could make."""

    def _goldens(self) -> dict[str, dict[str, object]]:
        payload = json.loads(GOLDENS_PATH.read_text(encoding="utf-8"))
        pairs: dict[str, dict[str, object]] = payload["pairs"]
        return pairs

    def test_yates_corrected_chi_square_would_fail_goldens(self) -> None:
        golden = self._goldens()["ALPHADRUG_x_Nausea"]
        a, b, c, d = 7, 2, 4, 7
        n = a + b + c + d
        yates = n * (abs(a * d - b * c) - n / 2) ** 2 / ((a + b) * (c + d) * (a + c) * (b + d))
        assert abs(yates - float(str(golden["chi_square"]))) > 0.5

    def test_90pct_z_would_fail_golden_cis(self) -> None:
        golden = self._goldens()["ALPHADRUG_x_Nausea"]
        a, b, c, d = 7, 2, 4, 7
        wrong_z = 1.644854  # 90% two-sided quantile instead of 95%
        se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
        wrong_high = math.exp(math.log((a * d) / (b * c)) + wrong_z * se)
        assert abs(wrong_high - float(str(golden["ror_ci_high"]))) > 1.0

    def test_row_swapped_prr_would_fail_goldens(self) -> None:
        golden = self._goldens()["GAMMADRUG_x_Rash"]
        a, b, c, d = 3, 2, 2, 13
        swapped = (c / (c + d)) / (a / (a + b))  # inverted orientation
        assert abs(swapped - float(str(golden["prr"]))) > 1.0
