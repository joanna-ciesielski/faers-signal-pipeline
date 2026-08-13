"""Scenario + property tests for the dedup centerpiece (written first).

Every scenario carries a plain-English docstring describing the real-world
situation it models. The property tests at the bottom are the CI-gated
invariants from the build plan: resolution is a pure function of the *set*
of sightings and deletions — row order, load order, and repetition must
never change the outcome.
"""

from __future__ import annotations

import polars as pl
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from faers_signal_pipeline.dedup.resolve import resolve_current

# ---------------------------------------------------------------------------
# helpers


def sightings(*rows: tuple[str, str, str]) -> pl.DataFrame:
    """Build a sightings frame from (caseid, caseversion, quarter) tuples."""
    return pl.DataFrame(
        [(c, v, q, f"{c}{v}") for c, v, q in rows],
        schema={
            "caseid": pl.String,
            "caseversion": pl.String,
            "quarter": pl.String,
            "primaryid": pl.String,
        },
        orient="row",
    )


def deletions(*rows: tuple[str, str]) -> pl.DataFrame:
    return pl.DataFrame(
        list(rows) or None,
        schema={"caseid": pl.String, "quarter": pl.String},
        orient="row",
    )


def current_as_dict(frame: pl.DataFrame) -> dict[str, tuple[str, str]]:
    """caseid -> (winning caseversion, source quarter)."""
    return {
        row["caseid"]: (row["caseversion"], row["quarter"]) for row in frame.iter_rows(named=True)
    }


# ---------------------------------------------------------------------------
# scenarios


class TestScenarios:
    def test_new_case(self) -> None:
        """A case reported once, never revised or deleted, is current as-is."""
        result = resolve_current(sightings(("100", "1", "2026q1")), deletions())
        assert current_as_dict(result.current) == {"100": ("1", "2026q1")}

    def test_same_quarter_revision(self) -> None:
        """FDA publishes v1 and v2 of a case in the same quarterly extract:
        the higher version is current; both remain in history."""
        result = resolve_current(
            sightings(("100", "1", "2026q1"), ("100", "2", "2026q1")), deletions()
        )
        assert current_as_dict(result.current) == {"100": ("2", "2026q1")}
        assert result.stats["version_sightings"] == 2

    def test_cross_quarter_revision(self) -> None:
        """A follow-up version arrives in a later quarter and supersedes the
        original."""
        result = resolve_current(
            sightings(("100", "1", "2026q1"), ("100", "2", "2026q2")), deletions()
        )
        assert current_as_dict(result.current) == {"100": ("2", "2026q2")}

    def test_deletion(self) -> None:
        """A case is reported, then appears on a later quarter's deleted-cases
        list: it leaves current_cases entirely (history is kept upstream)."""
        result = resolve_current(sightings(("100", "1", "2026q1")), deletions(("100", "2026q2")))
        assert current_as_dict(result.current) == {}
        assert result.effective_deletions.get_column("caseid").to_list() == ["100"]

    def test_revision_after_deletion_resurrects(self) -> None:
        """FDA deletes a case, then publishes a new version in a strictly
        later quarter: the new information resurrects the case (our documented
        policy choice — see docs/dedup-policy.md)."""
        result = resolve_current(
            sightings(("100", "1", "2025q4"), ("100", "2", "2026q2")),
            deletions(("100", "2026q1")),
        )
        assert current_as_dict(result.current) == {"100": ("2", "2026q2")}
        assert result.stats["resurrected_cases"] == 1

    def test_same_quarter_version_and_deletion_deletes(self) -> None:
        """A version sighting and a deletion in the same quarter: deletion
        wins (documented tie rule — deleting is the stronger, rarer signal)."""
        result = resolve_current(
            sightings(("100", "1", "2026q1"), ("100", "2", "2026q2")),
            deletions(("100", "2026q2")),
        )
        assert current_as_dict(result.current) == {}

    def test_late_arriving_older_version_is_ignored(self) -> None:
        """An older version number arrives in a later quarter (out-of-order
        publication): the higher version stays current regardless of arrival
        order — version numbers rank information, quarters do not."""
        result = resolve_current(
            sightings(("100", "2", "2026q1"), ("100", "1", "2026q2")), deletions()
        )
        assert current_as_dict(result.current) == {"100": ("2", "2026q1")}
        assert result.stats["superseded_sightings"] == 1

    def test_same_version_republished_latest_quarter_wins(self) -> None:
        """The same version appears in two quarterly extracts: the latest
        quarter's copy is the one current points at (later publication
        supersedes earlier for identical version numbers)."""
        result = resolve_current(
            sightings(("100", "1", "2026q1"), ("100", "1", "2026q2")), deletions()
        )
        assert current_as_dict(result.current) == {"100": ("1", "2026q2")}

    def test_deletion_of_never_seen_case_recorded_not_error(self) -> None:
        """A deleted-cases list names a CASEID we never saw a version for:
        recorded and counted, affects nothing else."""
        result = resolve_current(sightings(("100", "1", "2026q1")), deletions(("999", "2026q1")))
        assert current_as_dict(result.current) == {"100": ("1", "2026q1")}
        assert result.stats["never_seen_deletions"] == 1

    def test_multiple_independent_cases(self) -> None:
        """Rules apply per-case, never across cases."""
        result = resolve_current(
            sightings(
                ("100", "1", "2026q1"),
                ("200", "1", "2026q1"),
                ("200", "2", "2026q2"),
                ("300", "1", "2026q1"),
            ),
            deletions(("300", "2026q2")),
        )
        assert current_as_dict(result.current) == {
            "100": ("1", "2026q1"),
            "200": ("2", "2026q2"),
        }

    def test_exact_duplicate_sightings_collapse(self) -> None:
        """The same (caseid, version, quarter) row appearing twice (in-file
        duplicate) collapses to one sighting; the duplication is counted."""
        result = resolve_current(
            sightings(("100", "1", "2026q1"), ("100", "1", "2026q1")), deletions()
        )
        assert current_as_dict(result.current) == {"100": ("1", "2026q1")}
        assert result.stats["duplicate_sightings"] == 1

    def test_empty_inputs(self) -> None:
        """No data in, no data out — no crashes on empty frames."""
        result = resolve_current(sightings(), deletions())
        assert result.current.height == 0
        assert result.effective_deletions.height == 0


# ---------------------------------------------------------------------------
# CI-gated invariants (the build plan's order-independence gate, pure level)


def _sorted_rows(frame: pl.DataFrame) -> list[tuple[str, ...]]:
    return sorted(tuple(row) for row in frame.iter_rows())


class TestInvariants:
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        events=st.lists(
            st.tuples(
                st.sampled_from(["100", "200", "300"]),  # caseid
                st.sampled_from(["1", "2", "3", "10"]),  # caseversion
                st.sampled_from(["2025q4", "2026q1", "2026q2", "2026q3"]),
            ),
            max_size=25,
        ),
        dels=st.lists(
            st.tuples(
                st.sampled_from(["100", "200", "300", "999"]),
                st.sampled_from(["2025q4", "2026q1", "2026q2", "2026q3"]),
            ),
            max_size=8,
        ),
        seed=st.randoms(use_true_random=False),
    )
    def test_resolution_is_order_independent(
        self,
        events: list[tuple[str, str, str]],
        dels: list[tuple[str, str]],
        seed: object,
    ) -> None:
        """THE gate: any permutation of the same sightings and deletions —
        i.e. any quarter load order, any file order — resolves identically."""
        baseline = resolve_current(sightings(*events), deletions(*dels))

        shuffled_events = list(events)
        shuffled_dels = list(dels)
        seed.shuffle(shuffled_events)  # type: ignore[attr-defined]
        seed.shuffle(shuffled_dels)  # type: ignore[attr-defined]
        permuted = resolve_current(sightings(*shuffled_events), deletions(*shuffled_dels))

        assert _sorted_rows(baseline.current) == _sorted_rows(permuted.current)
        assert _sorted_rows(baseline.effective_deletions) == _sorted_rows(
            permuted.effective_deletions
        )
        assert baseline.stats == permuted.stats

    def test_resolution_is_idempotent_on_repetition(self) -> None:
        """Feeding the same sightings twice (a re-loaded quarter) changes
        nothing but the duplicate count."""
        events = [("100", "1", "2026q1"), ("100", "2", "2026q2"), ("200", "1", "2026q1")]
        once = resolve_current(sightings(*events), deletions())
        twice = resolve_current(sightings(*events, *events), deletions())
        assert _sorted_rows(once.current) == _sorted_rows(twice.current)

    def test_resolution_is_deterministic(self) -> None:
        """Same input object, two calls, identical output including order."""
        frame = sightings(("100", "2", "2026q1"), ("100", "1", "2026q2"))
        first = resolve_current(frame, deletions(("999", "2026q1")))
        second = resolve_current(frame, deletions(("999", "2026q1")))
        assert first.current.equals(second.current)
        assert first.stats == second.stats


class TestNumericOrdering:
    def test_version_10_beats_version_9(self) -> None:
        """Version ordering is numeric, never lexicographic: '10' > '9'
        even though '10' < '9' as strings."""
        result = resolve_current(
            sightings(("100", "9", "2026q1"), ("100", "10", "2026q2")), deletions()
        )
        assert current_as_dict(result.current) == {"100": ("10", "2026q2")}

    def test_second_deletion_after_resurrection_deletes_again(self) -> None:
        """Delete, resurrect by a later version, delete again in a yet later
        quarter: the case ends deleted (rules re-apply on the full history)."""
        result = resolve_current(
            sightings(("100", "1", "2025q1"), ("100", "2", "2025q3")),
            deletions(("100", "2025q2"), ("100", "2025q4")),
        )
        assert current_as_dict(result.current) == {}

    def test_stats_account_for_every_input_row(self) -> None:
        """Accounting identity: duplicates + superseded + unique cases =
        total sightings, and current + deleted = unique cases."""
        result = resolve_current(
            sightings(
                ("100", "1", "2026q1"),
                ("100", "1", "2026q1"),
                ("100", "2", "2026q1"),
                ("200", "1", "2026q1"),
            ),
            deletions(("200", "2026q1"), ("999", "2026q1")),
        )
        stats = result.stats
        assert (
            stats["duplicate_sightings"]
            + stats["superseded_sightings"]
            + stats["unique_cases_seen"]
            == stats["version_sightings"]
        )
        assert stats["current_cases"] + stats["deleted_cases"] == stats["unique_cases_seen"]
