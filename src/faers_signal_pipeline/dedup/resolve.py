"""Pure resolution of current cases from version sightings and deletions.

The resolution is a function of the *set* of inputs: row order, quarter
load order, and repetition never change the outcome (property-tested).

Rules (full rationale + FDA basis in docs/dedup-policy.md):

1. Higher CASEVERSION wins — version numbers rank information; arrival
   quarter does not. A late-arriving older version never displaces a
   higher one.
2. The same version republished in several quarters resolves to the latest
   quarter's sighting (later publication supersedes for equal versions).
3. A case is deleted iff its latest deletion quarter >= its latest sighting
   quarter. Equal quarter -> deletion wins (tie rule, ours). A sighting in
   a strictly later quarter resurrects the case (policy choice, ours).
4. Exact duplicate sightings collapse deterministically (sort + keep last)
   and are counted, never silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

#: Sortable integer key for a quarter label: "2026q2" -> 20262.
_QKEY = (
    pl.col("quarter").str.slice(0, 4).cast(pl.Int64) * 10
    + pl.col("quarter").str.slice(5, 1).cast(pl.Int64)
).alias("qkey")

#: Blank caseversion is the legacy-AERS "initial report" (approved policy,
#: docs/dedup-policy.md): it resolves as version 0. Modern eras never stage
#: a blank caseversion (their contracts require it), so the fill is inert
#: for them.
_VERSION_INT = pl.col("caseversion").cast(pl.Int64).fill_null(0).alias("version_int")

#: First quarter of case/version identity (FAERS era). Cross-era ordering
#: rule (approved 2026-08-17): ANY FAERS-era sighting supersedes ANY
#: legacy-AERS sighting of the same case — chronologically sound, since
#: every FAERS-era quarter postdates every legacy quarter, and legacy
#: FOLL_SEQ numbers are not comparable to FAERS caseversion numbers.
_FAERS_ERA_QKEY = 20124
_ERA_RANK = (pl.col("qkey") >= _FAERS_ERA_QKEY).cast(pl.Int64).alias("era_rank")


@dataclass(frozen=True, slots=True)
class Resolution:
    """Outcome of one resolution pass."""

    #: One row per living case: caseid, caseversion, quarter, primaryid —
    #: the winning sighting (its quarter locates the payload in staging).
    current: pl.DataFrame
    #: Cases removed by an effective deletion: caseid, deletion quarter.
    effective_deletions: pl.DataFrame
    #: Honest accounting; every input row is explained by these numbers.
    stats: dict[str, int]


def resolve_current(sightings: pl.DataFrame, deletions: pl.DataFrame) -> Resolution:
    """Resolve current cases from all version sightings + deletion events.

    ``sightings``: columns caseid, caseversion (digits), quarter (label),
    primaryid — one row per version-per-quarter observation, across every
    loaded quarter. ``deletions``: columns caseid, quarter.
    """
    total = sightings.height

    keyed = (
        sightings.with_columns(_QKEY, _VERSION_INT)
        .with_columns(_ERA_RANK)
        # Deterministic collapse of duplicates: full sort then keep the last
        # row per (caseid, version, quarter) — identical under any input
        # order. Duplicates are counted below, never silently dropped.
        .sort(["caseid", "version_int", "qkey", "primaryid"])
        .unique(subset=["caseid", "version_int", "qkey"], keep="last", maintain_order=True)
    )
    duplicate_sightings = total - keyed.height

    # Latest sighting quarter per case (V*), regardless of version number:
    # this is what deletions compare against and what resurrection tests.
    vstar = keyed.group_by("caseid").agg(pl.col("qkey").max().alias("vstar"))

    # Winner per case: era first (FAERS-era sightings supersede legacy),
    # then highest version; among equal versions, latest quarter.
    winners = (
        keyed.sort(["caseid", "era_rank", "version_int", "qkey"])
        .group_by("caseid", maintain_order=True)
        .last()
    )
    superseded_sightings = keyed.height - winners.height

    # Effective deletions: latest deletion quarter per case (D*), compared
    # against V*. D* >= V* -> deleted (same-quarter tie: deletion wins).
    dstar = (
        deletions.with_columns(_QKEY)
        .group_by("caseid")
        .agg(pl.col("qkey").max().alias("dstar"), pl.col("quarter").max().alias("quarter"))
    )
    judged = dstar.join(vstar, on="caseid", how="left")
    never_seen = judged.filter(pl.col("vstar").is_null())
    effective = judged.filter(pl.col("vstar").is_not_null() & (pl.col("dstar") >= pl.col("vstar")))
    resurrected = judged.filter(pl.col("vstar").is_not_null() & (pl.col("dstar") < pl.col("vstar")))

    current = (
        winners.join(effective.select("caseid"), on="caseid", how="anti")
        .select("caseid", "caseversion", "quarter", "primaryid")
        .sort("caseid")
    )

    stats = {
        "version_sightings": total,
        "duplicate_sightings": duplicate_sightings,
        "superseded_sightings": superseded_sightings,
        "unique_cases_seen": winners.height,
        "current_cases": current.height,
        "deleted_cases": effective.height,
        "resurrected_cases": resurrected.height,
        "never_seen_deletions": never_seen.height,
    }
    return Resolution(
        current=current,
        effective_deletions=effective.select("caseid", "quarter").sort("caseid"),
        stats=stats,
    )
