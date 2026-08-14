"""Always-on precondition tests for the orchestration CLIs (no server)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEMPORAL_ADDRESS", raising=False)


class TestRunWorkerCli:
    def test_requires_database_url(self) -> None:
        from run_worker import main

        assert main([]) == 2


class TestPipelineWorkflowCli:
    def test_requires_database_url(self) -> None:
        from pipeline_workflow import main

        assert main(["ingest", "2026q2"]) == 2

    def test_rejects_bad_quarter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pipeline_workflow import main

        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        assert main(["ingest", "not-a-quarter"]) == 2

    def test_ingest_takes_exactly_one_quarter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pipeline_workflow import main

        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        assert main(["ingest", "2026q1", "2026q2"]) == 2


class TestManageScheduleCli:
    def test_create_requires_database_url(self) -> None:
        from manage_schedule import main

        assert main(["create"]) == 2
