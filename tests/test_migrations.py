"""Migration runner: ordered plain-SQL files, tracked, checksummed.

Written before the runner (standing rule: gates precede code). The
invariants gated here:

- A fresh apply creates every cross-cutting table the pipeline needs.
- Re-applying is a no-op (idempotent; zero newly applied).
- An edited already-applied file is refused loudly (checksum drift) —
  history is immutable; changes are new migration files.
- Files are strictly ordered with unique numeric prefixes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from tests.conftest import database_url

DATABASE_URL = database_url()
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not configured")

TEST_SCHEMA = "pytest_migrations"

#: Every table the migrations must provide (staging tables excluded: those
#: are generated from the era layout spec at load time — single source of
#: truth in layout.py, documented in db/migrations/README).
EXPECTED_TABLES = {
    "schema_migrations",
    "runs",
    "quarantine",
    "stg_deleted_cases",
    "case_versions",
    "current_cases",
    "drug_map",
    "signal_stats",
    "audit_log",
    "drug_profiles",
}


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL) as connection:
        connection.autocommit = True
        with connection.cursor() as cur, connection.transaction():
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
            cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
            cur.execute(f"SET search_path TO {TEST_SCHEMA}")
        yield connection


def table_names(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s",
            (TEST_SCHEMA,),
        )
        return {row[0] for row in cur.fetchall()}


class TestApply:
    def test_fresh_apply_creates_expected_tables(self, conn: psycopg.Connection) -> None:
        from faers_signal_pipeline.db.migrate import apply_migrations

        report = apply_migrations(conn)
        assert report.newly_applied == report.total_migrations
        assert report.total_migrations >= 7
        assert table_names(conn) >= EXPECTED_TABLES

    def test_reapply_is_noop(self, conn: psycopg.Connection) -> None:
        from faers_signal_pipeline.db.migrate import apply_migrations

        first = apply_migrations(conn)
        second = apply_migrations(conn)
        assert first.newly_applied == first.total_migrations
        assert second.newly_applied == 0
        assert second.total_migrations == first.total_migrations

    def test_tracking_rows_match_files(self, conn: psycopg.Connection) -> None:
        from faers_signal_pipeline.db.migrate import apply_migrations, migration_files

        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT version, name, sha256 FROM schema_migrations ORDER BY version")
            rows = cur.fetchall()
        files = migration_files()
        assert [row[0] for row in rows] == [f.version for f in files]
        assert [row[1] for row in rows] == [f.name for f in files]
        assert [row[2] for row in rows] == [f.sha256 for f in files]


class TestDrift:
    def test_checksum_drift_is_refused(self, conn: psycopg.Connection) -> None:
        from faers_signal_pipeline.db.migrate import MigrationDriftError, apply_migrations

        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute("UPDATE schema_migrations SET sha256 = 'tampered' WHERE version = 1")
        with pytest.raises(MigrationDriftError, match="0001"):
            apply_migrations(conn)

    def test_unknown_applied_version_is_refused(self, conn: psycopg.Connection) -> None:
        from faers_signal_pipeline.db.migrate import MigrationDriftError, apply_migrations

        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migrations (version, name, sha256)"
                " VALUES (9999, 'phantom', 'x')"
            )
        with pytest.raises(MigrationDriftError, match="9999"):
            apply_migrations(conn)


class TestCli:
    @pytest.fixture
    def cli_env(
        self, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> psycopg.Connection:
        separator = "&" if "?" in DATABASE_URL else "?"
        monkeypatch.setenv(
            "DATABASE_URL",
            f"{DATABASE_URL}{separator}options=-csearch_path%3D{TEST_SCHEMA}",
        )
        return conn

    def test_apply_then_noop(
        self, cli_env: psycopg.Connection, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from migrate import main

        assert main([]) == 0
        first = capsys.readouterr().out
        assert "newly applied" in first
        assert " 0 newly applied" not in first
        assert main([]) == 0
        assert " 0 newly applied" in capsys.readouterr().out

    def test_drift_exits_nonzero(
        self, cli_env: psycopg.Connection, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from migrate import main

        assert main([]) == 0
        cli_env.execute(f"SET search_path TO {TEST_SCHEMA}")
        cli_env.execute("UPDATE schema_migrations SET sha256 = 'tampered' WHERE version = 1")
        assert main([]) == 1
        assert "checksum" in capsys.readouterr().err


class TestFiles:
    def test_files_are_strictly_ordered_and_unique(self) -> None:
        from faers_signal_pipeline.db.migrate import migration_files

        files = migration_files()
        versions = [f.version for f in files]
        assert versions == sorted(versions)
        assert len(versions) == len(set(versions)), "duplicate migration version"
        for f in files:
            assert f.path.name == f"{f.version:04d}_{f.name}.sql"

    def test_migrations_dir_contains_only_sql_and_readme(self) -> None:
        from faers_signal_pipeline.db.migrate import MIGRATIONS_DIR

        stray = [
            p.name
            for p in Path(MIGRATIONS_DIR).iterdir()
            if p.suffix != ".sql" and p.name != "README.md"
        ]
        assert stray == []
