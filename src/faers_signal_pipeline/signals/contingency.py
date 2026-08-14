"""Case-level 2x2 contingency construction — pure functions over frames.

Counting policy (the part hand-verifiable against the synthetic corpus):

- Unit of counting = the deduplicated CASE (one row of current_cases). A
  case contributes each (rxcui, reaction PT) pair AT MOST ONCE, no matter
  how many drug or reaction rows its winning version carries. Row-level
  counting would double-count multi-row reports — the classic FAERS error.
- Drug identity = RXCUI (drug_map, status='matched'). Rows whose names did
  not map are EXCLUDED from drug-side counting and the exclusion is
  counted and reported — never silently absorbed into the margins.
- Reaction identity = the MedDRA PT string exactly as published
  (strings-as-published only; ADR 0004).
- Cells: a = cases with drug AND reaction; b = drug without reaction;
  c = reaction without drug; d = neither. N = all current cases.
- Threshold: pairs with a >= min_count (default 3, Evans 2001) are kept;
  the number of excluded pairs is reported.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

DEFAULT_MIN_COUNT = 3


@dataclass(frozen=True, slots=True)
class ContingencyResult:
    """Per-pair 2x2 cells plus honest accounting."""

    #: columns: rxcui, pt, a, b, c, d (a >= min_count)
    pairs: pl.DataFrame
    total_cases: int
    stats: dict[str, int]


def build_contingency(
    case_drugs: pl.DataFrame,  # columns: caseid, rxcui
    case_reactions: pl.DataFrame,  # columns: caseid, pt
    total_cases: int,
    min_count: int = DEFAULT_MIN_COUNT,
) -> ContingencyResult:
    """Build all qualifying (rxcui, pt) 2x2 tables at case level."""
    drugs = case_drugs.unique()
    reactions = case_reactions.unique()

    drug_totals = drugs.group_by("rxcui").agg(pl.len().alias("drug_cases"))
    reaction_totals = reactions.group_by("pt").agg(pl.len().alias("reaction_cases"))

    together = drugs.join(reactions, on="caseid").group_by(["rxcui", "pt"]).agg(pl.len().alias("a"))
    observed_pairs = together.height
    qualifying = together.filter(pl.col("a") >= min_count)

    pairs = (
        qualifying.join(drug_totals, on="rxcui")
        .join(reaction_totals, on="pt")
        .with_columns(
            (pl.col("drug_cases") - pl.col("a")).alias("b"),
            (pl.col("reaction_cases") - pl.col("a")).alias("c"),
        )
        .with_columns((pl.lit(total_cases) - pl.col("a") - pl.col("b") - pl.col("c")).alias("d"))
        .select("rxcui", "pt", "a", "b", "c", "d")
        .sort(["rxcui", "pt"])
    )

    return ContingencyResult(
        pairs=pairs,
        total_cases=total_cases,
        stats={
            "total_cases": total_cases,
            "cases_with_mapped_drug": drugs.get_column("caseid").n_unique(),
            "cases_with_reaction": reactions.get_column("caseid").n_unique(),
            "observed_pairs": observed_pairs,
            "qualifying_pairs": qualifying.height,
            "below_threshold_pairs": observed_pairs - qualifying.height,
        },
    )
