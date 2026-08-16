"""Always-on precondition tests for the Phase 6 CLIs (no database)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


class TestMigrateCli:
    def test_requires_database_url(self) -> None:
        from migrate import main

        assert main([]) == 2


class TestBuildEmbeddingsCli:
    def test_requires_database_url(self) -> None:
        from build_embeddings import main

        assert main(["--embedder", "stub"]) == 2

    def test_stub_embedder_needs_no_extra(self) -> None:
        from build_embeddings import make_embedder

        assert make_embedder("stub").model_name.startswith("stub-")


class TestSemanticSearchCli:
    def test_requires_database_url(self) -> None:
        from semantic_search import main

        assert main(["query", "--embedder", "stub"]) == 2
