"""Pure pre-clean functions: written before the code they specify.

No fuzzy matching lives here (ADR 0006): every transformation is a fixed,
inspectable rule — whitespace, case, trailing punctuation, and a cited list
of trailing salt/hydrate designations.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from faers_signal_pipeline.normalize.clean import candidate_names, clean_name


class TestCleanName:
    def test_uppercases_and_trims(self) -> None:
        assert clean_name("  aspirin  ") == "ASPIRIN"

    def test_collapses_internal_whitespace(self) -> None:
        assert clean_name("ACETAMINOPHEN   AND\tCODEINE") == "ACETAMINOPHEN AND CODEINE"

    def test_strips_trailing_periods(self) -> None:
        assert clean_name("ASPIRIN.") == "ASPIRIN"

    def test_empty_and_whitespace_only_become_empty(self) -> None:
        assert clean_name("") == ""
        assert clean_name("   ") == ""

    def test_latin1_bytes_survive_cleaning(self) -> None:
        # 8-bit bytes pass through unchanged apart from case-folding; the
        # idempotence property below pins the exact behavior.
        cleaned = clean_name("sjögren tablet")
        assert cleaned == "SJÖGREN TABLET"

    @given(st.text(max_size=60))
    def test_clean_is_idempotent(self, raw: str) -> None:
        assert clean_name(clean_name(raw)) == clean_name(raw)


class TestCandidateNames:
    def test_plain_name_yields_single_candidate(self) -> None:
        assert candidate_names("aspirin") == ("ASPIRIN",)

    def test_salt_suffix_yields_stripped_second_candidate(self) -> None:
        assert candidate_names("METFORMIN HYDROCHLORIDE") == (
            "METFORMIN HYDROCHLORIDE",
            "METFORMIN",
        )

    def test_hydrate_suffix_stripped(self) -> None:
        assert candidate_names("AZITHROMYCIN MONOHYDRATE") == (
            "AZITHROMYCIN MONOHYDRATE",
            "AZITHROMYCIN",
        )

    def test_only_trailing_token_is_considered(self) -> None:
        # "SODIUM CHLORIDE" is itself a substance: stripping the trailing
        # salt token would leave bare "SODIUM", still a name — allowed as a
        # *fallback* candidate only, never a replacement.
        assert candidate_names("SODIUM CHLORIDE") == ("SODIUM CHLORIDE", "SODIUM")

    def test_single_token_salt_name_not_stripped_to_empty(self) -> None:
        assert candidate_names("SODIUM") == ("SODIUM",)

    def test_empty_input_yields_nothing(self) -> None:
        assert candidate_names("   ") == ()

    def test_candidates_are_deduplicated(self) -> None:
        assert candidate_names("ASPIRIN") == ("ASPIRIN",)
