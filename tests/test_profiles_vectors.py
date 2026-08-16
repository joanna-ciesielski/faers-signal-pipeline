"""Per-drug safety-profile text, embeddings, and semantic search.

Written before the code. Contracts gated here:

- Profile text is DETERMINISTIC: byte-identical across rebuilds from the
  same database state, versioned format, stable ordering rules
  (ror_ci_low DESC, pt ASC; display name = lexicographically smallest
  matched name_key — a deliberate, drift-free choice documented in
  signals/profiles.py).
- Embedding bookkeeping is cache-first like the RxNav mapper: unchanged
  profile + same model => zero re-embeds on a second run.
- The stub embedder is deterministic and unit-norm, so tests are offline
  and reproducible; the real bge-small-en-v1.5 embedder is an optional
  extra exercised on the maintainer machine only.
- Semantic search returns (distance ASC, rxcui ASC) with an optional
  lexical must-contain filter (the "hybrid" in hybrid search).
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import psycopg
import pytest
from tests.conftest import database_url

DATABASE_URL = database_url()
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not configured")

TEST_SCHEMA = "pytest_vectors"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL) as connection:
        connection.autocommit = True
        with connection.cursor() as cur, connection.transaction():
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
            cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
            cur.execute(f"SET search_path TO {TEST_SCHEMA}")
        yield connection


@pytest.fixture
def migrated(conn: psycopg.Connection) -> psycopg.Connection:
    from faers_signal_pipeline.db.migrate import apply_migrations

    apply_migrations(conn)
    seed(conn)
    return conn


def seed(conn: psycopg.Connection) -> None:
    """Two drugs with distinct signal shapes; names chosen so the
    display-name rule (smallest matched name_key) is actually exercised."""
    rows = [
        ("2026q2", "100", "Nausea", 9, 1, 5, 100, 4.5),
        ("2026q2", "100", "Rash", 3, 7, 2, 103, 1.2),
        ("2026q2", "100", "Headache", 3, 7, 2, 103, 1.2),  # tie with Rash
        ("2026q2", "200", "Meningioma", 12, 2, 1, 100, 9.9),
    ]
    for cutoff, rxcui, pt, a, b, c, ror_low in (
        (r[0], r[1], r[2], r[3], r[4], r[5], r[7]) for r in rows
    ):
        conn.execute(
            "INSERT INTO signal_stats"
            " (cutoff_quarter, rxcui, pt, a, b, c, d, ror_ci_low)"
            " VALUES (%s, %s, %s, %s, %s, %s, 100, %s)",
            (cutoff, rxcui, pt, a, b, c, ror_low),
        )
    name_rows: tuple[tuple[str, str | None, str], ...] = (
        ("ZETA BRAND", "100", "matched"),
        ("ALPHACILLIN", "100", "matched"),  # smallest key -> display name
        ("UNRELATED", None, "no_match"),
        ("BETADRUG", "200", "matched"),
    )
    for name_key, mapped_rxcui, status in name_rows:
        conn.execute(
            "INSERT INTO drug_map (name_key, rxcui, status) VALUES (%s, %s, %s)",
            (name_key, mapped_rxcui, status),
        )


class TestProfileText:
    def test_deterministic_and_versioned(self, migrated: psycopg.Connection) -> None:
        from faers_signal_pipeline.signals.profiles import build_profiles

        first = build_profiles(migrated)
        texts_1 = {
            r[0]: r[1]
            for r in migrated.execute("SELECT rxcui, profile_text FROM drug_profiles").fetchall()
        }
        second = build_profiles(migrated)
        texts_2 = {
            r[0]: r[1]
            for r in migrated.execute("SELECT rxcui, profile_text FROM drug_profiles").fetchall()
        }
        assert first.profiles_built == 2
        assert second.profiles_built == 2  # rebuilt, but...
        assert texts_1 == texts_2  # ...byte-identical
        assert all(t.startswith("profile-version: 1\n") for t in texts_1.values())

    def test_ordering_and_display_name_rules(self, migrated: psycopg.Connection) -> None:
        from faers_signal_pipeline.signals.profiles import build_profiles

        build_profiles(migrated)
        row = migrated.execute(
            "SELECT display_name, profile_text FROM drug_profiles WHERE rxcui = '100'"
        ).fetchone()
        assert row is not None
        display_name, text = row
        assert display_name == "ALPHACILLIN"
        # ror_ci_low DESC puts Nausea first; the Headache/Rash tie breaks pt ASC.
        nausea = text.index("Nausea")
        headache = text.index("Headache")
        rash = text.index("Rash")
        assert nausea < headache < rash

    def test_unchanged_state_keeps_sha(self, migrated: psycopg.Connection) -> None:
        from faers_signal_pipeline.signals.profiles import build_profiles

        build_profiles(migrated)
        sha_1 = migrated.execute(
            "SELECT profile_sha256 FROM drug_profiles WHERE rxcui = '100'"
        ).fetchone()
        build_profiles(migrated)
        sha_2 = migrated.execute(
            "SELECT profile_sha256 FROM drug_profiles WHERE rxcui = '100'"
        ).fetchone()
        assert sha_1 == sha_2


class TestHashEmbedder:
    def test_deterministic_unit_norm_correct_dim(self) -> None:
        from faers_signal_pipeline.vectors.embed import EMBEDDING_DIM, HashEmbedder

        embedder = HashEmbedder()
        [v1] = embedder.embed(["metformin nausea"])
        [v2] = embedder.embed(["metformin nausea"])
        [v3] = embedder.embed(["something else"])
        assert v1 == v2
        assert v1 != v3
        assert len(v1) == EMBEDDING_DIM
        assert math.isclose(math.hypot(*v1), 1.0, rel_tol=1e-9)


class TestEmbeddingBookkeeping:
    def test_second_run_embeds_nothing(self, migrated: psycopg.Connection) -> None:
        from faers_signal_pipeline.signals.profiles import build_profiles
        from faers_signal_pipeline.vectors.embed import HashEmbedder, embed_profiles

        build_profiles(migrated)
        first = embed_profiles(migrated, HashEmbedder())
        second = embed_profiles(migrated, HashEmbedder())
        assert first.embedded == 2
        assert second.embedded == 0
        assert second.up_to_date == 2

    def test_changed_profile_reembeds_only_that_drug(self, migrated: psycopg.Connection) -> None:
        from faers_signal_pipeline.signals.profiles import build_profiles
        from faers_signal_pipeline.vectors.embed import HashEmbedder, embed_profiles

        build_profiles(migrated)
        embed_profiles(migrated, HashEmbedder())
        migrated.execute(
            "INSERT INTO signal_stats"
            " (cutoff_quarter, rxcui, pt, a, b, c, d, ror_ci_low)"
            " VALUES ('2026q2', '200', 'Alopecia', 4, 1, 1, 100, 2.0)"
        )
        build_profiles(migrated)
        rerun = embed_profiles(migrated, HashEmbedder())
        assert rerun.embedded == 1  # drug 200 only
        assert rerun.up_to_date == 1

    def test_model_change_reembeds_everything(self, migrated: psycopg.Connection) -> None:
        from faers_signal_pipeline.signals.profiles import build_profiles
        from faers_signal_pipeline.vectors.embed import HashEmbedder, embed_profiles

        build_profiles(migrated)
        embed_profiles(migrated, HashEmbedder())
        rerun = embed_profiles(migrated, HashEmbedder(model_name="stub-v2"))
        assert rerun.embedded == 2


class TestSemanticSearch:
    def test_self_query_ranks_self_first_and_orders_deterministically(
        self, migrated: psycopg.Connection
    ) -> None:
        from faers_signal_pipeline.signals.profiles import build_profiles
        from faers_signal_pipeline.vectors.embed import (
            HashEmbedder,
            embed_profiles,
            semantic_search,
        )

        build_profiles(migrated)
        embed_profiles(migrated, HashEmbedder())
        text_100 = migrated.execute(
            "SELECT profile_text FROM drug_profiles WHERE rxcui = '100'"
        ).fetchone()
        assert text_100 is not None
        hits = semantic_search(migrated, HashEmbedder(), text_100[0], k=5)
        assert hits[0].rxcui == "100"
        assert math.isclose(hits[0].distance, 0.0, abs_tol=1e-6)
        assert [h.rxcui for h in hits] == ["100", "200"]

    def test_must_contain_filters_lexically(self, migrated: psycopg.Connection) -> None:
        from faers_signal_pipeline.signals.profiles import build_profiles
        from faers_signal_pipeline.vectors.embed import (
            HashEmbedder,
            embed_profiles,
            semantic_search,
        )

        build_profiles(migrated)
        embed_profiles(migrated, HashEmbedder())
        hits = semantic_search(migrated, HashEmbedder(), "anything", k=5, must_contain="Meningioma")
        assert [h.rxcui for h in hits] == ["200"]

    def test_cli_round_trip_with_stub(
        self,
        migrated: psycopg.Connection,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """build_embeddings then semantic_search, both via CLI, stub model."""
        from build_embeddings import main as build_main
        from semantic_search import main as search_main

        separator = "&" if "?" in DATABASE_URL else "?"
        monkeypatch.setenv(
            "DATABASE_URL",
            f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}",
        )
        assert build_main(["--embedder", "stub"]) == 0
        out = capsys.readouterr().out
        assert "built=2" in out
        assert "embedded=2" in out
        assert search_main(["anything", "--embedder", "stub", "--must-contain", "Meningioma"]) == 0
        out = capsys.readouterr().out
        assert "BETADRUG" in out
        assert "rxcui=200" in out

    def test_cli_search_without_embeddings_reports_empty(
        self,
        migrated: psycopg.Connection,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from semantic_search import main as search_main

        separator = "&" if "?" in DATABASE_URL else "?"
        monkeypatch.setenv(
            "DATABASE_URL",
            f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}",
        )
        assert search_main(["anything", "--embedder", "stub"]) == 1
        assert "no results" in capsys.readouterr().out

    def test_hnsw_index_exists(self, migrated: psycopg.Connection) -> None:
        row = migrated.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = %s"
            " AND tablename = 'drug_profiles' AND indexdef ILIKE '%%hnsw%%'",
            (TEST_SCHEMA,),
        ).fetchone()
        assert row is not None, "expected an HNSW index on drug_profiles.embedding"
