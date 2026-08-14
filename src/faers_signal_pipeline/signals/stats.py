"""Disproportionality statistics — pure functions, cited formulas.

2x2 contingency table per (drug, reaction) pair, case-level counts:

                reaction R    other reactions
    drug D          a               b
    other drugs     c               d

- PRR (proportional reporting ratio), Evans SJ, Waller PC, Davis S.
  "Use of proportional reporting ratios (PRRs) for signal generation from
  spontaneous adverse drug reaction reports." Pharmacoepidemiol Drug Saf
  2001;10(6):483-6.
      PRR = (a / (a + b)) / (c / (c + d))
      SE(ln PRR) = sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
      95% CI = exp(ln PRR +/- 1.96 * SE)

- ROR (reporting odds ratio), van Puijenbroek EP et al. "A comparison of
  measures of disproportionality for signal detection in spontaneous
  reporting systems for adverse drug reactions." Pharmacoepidemiol Drug
  Saf 2002;11(1):3-10.
      ROR = (a * d) / (b * c)
      SE(ln ROR) = sqrt(1/a + 1/b + 1/c + 1/d)
      95% CI = exp(ln ROR +/- 1.96 * SE)

- Chi-square: Pearson's chi-square with 1 df, WITHOUT Yates continuity
  correction (documented choice — must match the hand-computed goldens):
      chi2 = N * (a*d - b*c)^2 / ((a+b) * (c+d) * (a+c) * (b+d))

Zero guards: any statistic whose formula divides by a zero margin or takes
log of zero returns None rather than a fabricated number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_Z95 = 1.959963984540054  # two-sided 95% normal quantile


@dataclass(frozen=True, slots=True)
class Estimate:
    """A point estimate with its 95% confidence interval."""

    value: float
    ci_low: float
    ci_high: float


def prr(a: int, b: int, c: int, d: int) -> Estimate | None:
    """Proportional reporting ratio with 95% CI (Evans 2001)."""
    if a == 0 or c == 0 or (a + b) == 0 or (c + d) == 0:
        return None
    value = (a / (a + b)) / (c / (c + d))
    if value <= 0:
        return None
    se = math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
    log_value = math.log(value)
    return Estimate(
        value=value,
        ci_low=math.exp(log_value - _Z95 * se),
        ci_high=math.exp(log_value + _Z95 * se),
    )


def ror(a: int, b: int, c: int, d: int) -> Estimate | None:
    """Reporting odds ratio with 95% CI (van Puijenbroek 2002)."""
    if a == 0 or b == 0 or c == 0 or d == 0:
        return None
    value = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    log_value = math.log(value)
    return Estimate(
        value=value,
        ci_low=math.exp(log_value - _Z95 * se),
        ci_high=math.exp(log_value + _Z95 * se),
    )


def chi_square(a: int, b: int, c: int, d: int) -> float | None:
    """Pearson chi-square, 1 df, no continuity correction."""
    n = a + b + c + d
    denominator = (a + b) * (c + d) * (a + c) * (b + d)
    if n == 0 or denominator == 0:
        return None
    return n * (a * d - b * c) ** 2 / denominator
