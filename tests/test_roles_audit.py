"""Role isolation and the append-only audit trail.

Written before the migrations they gate. The role model (see
db/migrations/README):

- ``etl_writer``    — full DML on pipeline tables; INSERT-only on audit_log.
- ``readonly_analyst`` — SELECT on everything (including quarantine).
- ``readonly_web``  — SELECT only on the serving surface (signal_stats,
  drug_map, drug_profiles, runs). Deliberately NO access to staging or
  quarantine: those hold raw FAERS payloads, and the web tier must be
  unable to read them even if compromised (log-hygiene posture).

audit_log is append-only for every role INCLUDING superuser: enforced by
trigger, not just grants.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from tests.conftest import build_quarter_zip, database_url

from faers_signal_pipeline.quarter import Quarter

DATABASE_URL = database_url()
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not configured")

TEST_SCHEMA = "pytest_roles"
QUARTER = Quarter.parse("2026q2")


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
    return conn


@contextmanager
def acting_as(conn: psycopg.Connection, role: str) -> Iterator[psycopg.Connection]:
    """Run statements as ``role``; always restore, even after an error."""
    conn.execute(f"SET ROLE {role}")
    try:
        yield conn
    finally:
        conn.execute("RESET ROLE")


def denied(conn: psycopg.Connection, role: str, sql: str) -> bool:
    with acting_as(conn, role):
        try:
            conn.execute(sql)
        except psycopg.errors.InsufficientPrivilege:
            return True
    return False


def allowed(conn: psycopg.Connection, role: str, sql: str) -> bool:
    return not denied(conn, role, sql)


def seed_serving_rows(conn: psycopg.Connection) -> None:
    conn.execute(
        "INSERT INTO signal_stats (cutoff_quarter, rxcui, pt, a, b, c, d)"
        " VALUES ('2026q2', '1', 'Nausea', 3, 1, 1, 1)"
    )
    conn.execute("INSERT INTO drug_map (name_key, rxcui, status) VALUES ('ALPHA', '1', 'matched')")
    conn.execute(
        "INSERT INTO quarantine (quarter, source_member, scope, reason_codes, raw_payload)"
        " VALUES ('2026q2', 'x', 'row', 'test', 'RAW$LINE$PAYLOAD')"
    )


class TestRoleIsolation:
    def test_roles_exist(self, migrated: psycopg.Connection) -> None:
        with migrated.cursor() as cur:
            cur.execute(
                "SELECT rolname FROM pg_roles WHERE rolname IN"
                " ('etl_writer', 'readonly_web', 'readonly_analyst')"
            )
            assert {row[0] for row in cur.fetchall()} == {
                "etl_writer",
                "readonly_web",
                "readonly_analyst",
            }

    def test_readonly_web_sees_serving_surface_only(self, migrated: psycopg.Connection) -> None:
        seed_serving_rows(migrated)
        for sql in (
            "SELECT count(*) FROM signal_stats",
            "SELECT count(*) FROM drug_map",
            "SELECT count(*) FROM drug_profiles",
            "SELECT count(*) FROM runs",
        ):
            assert allowed(migrated, "readonly_web", sql), sql
        # The raw-payload surfaces are unreadable — by design, not omission.
        for sql in (
            "SELECT count(*) FROM quarantine",
            "SELECT count(*) FROM case_versions",
            "SELECT count(*) FROM current_cases",
            "SELECT count(*) FROM audit_log",
        ):
            assert denied(migrated, "readonly_web", sql), sql

    def test_readonly_roles_cannot_write(self, migrated: psycopg.Connection) -> None:
        for role in ("readonly_web", "readonly_analyst"):
            assert denied(
                migrated,
                role,
                "INSERT INTO signal_stats (cutoff_quarter, rxcui, pt, a, b, c, d)"
                " VALUES ('x', 'x', 'x', 0, 0, 0, 0)",
            ), role

    def test_readonly_analyst_reads_everything(self, migrated: psycopg.Connection) -> None:
        seed_serving_rows(migrated)
        for sql in (
            "SELECT count(*) FROM quarantine",
            "SELECT count(*) FROM signal_stats",
            "SELECT count(*) FROM case_versions",
            "SELECT count(*) FROM audit_log",
        ):
            assert allowed(migrated, "readonly_analyst", sql), sql

    def test_etl_writer_full_dml_except_audit_mutation(self, migrated: psycopg.Connection) -> None:
        with acting_as(migrated, "etl_writer"):
            migrated.execute(
                "INSERT INTO drug_map (name_key, rxcui, status) VALUES ('K', '1', 'matched')"
            )
            migrated.execute("UPDATE drug_map SET rxcui = '2' WHERE name_key = 'K'")
            migrated.execute("DELETE FROM drug_map WHERE name_key = 'K'")
            migrated.execute("TRUNCATE current_cases")
        assert denied(migrated, "etl_writer", "DELETE FROM audit_log")
        assert denied(migrated, "etl_writer", "UPDATE audit_log SET action = 'x'")


class TestAuditAppendOnly:
    def test_insert_allowed_mutation_blocked_even_for_owner(
        self, migrated: psycopg.Connection
    ) -> None:
        migrated.execute("INSERT INTO audit_log (action, object) VALUES ('test', 'audit-check')")
        # The migration-running role owns the table and bypasses grants —
        # the trigger is what makes append-only real.
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            migrated.execute("UPDATE audit_log SET action = 'tampered'")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            migrated.execute("DELETE FROM audit_log")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            migrated.execute("TRUNCATE audit_log")

    def test_audit_row_on_every_load(self, migrated: psycopg.Connection, tmp_path: Path) -> None:
        from faers_signal_pipeline.pipeline import load_quarter

        zip_path = build_quarter_zip(tmp_path / "q.zip", QUARTER)
        load_quarter(migrated, zip_path, QUARTER, report_dir=tmp_path / "reports")
        load_quarter(migrated, zip_path, QUARTER, report_dir=tmp_path / "reports")
        with migrated.cursor() as cur:
            cur.execute("SELECT count(*) FROM runs WHERE kind = 'stage_quarter'")
            runs = cur.fetchone()
            cur.execute(
                "SELECT count(*) FROM audit_log WHERE action = 'stage_quarter' AND quarter = %s",
                (QUARTER.label,),
            )
            audits = cur.fetchone()
        assert runs is not None and audits is not None
        assert runs[0] == 2  # loads are recorded per run, audit mirrors runs
        assert audits[0] == runs[0]

    def test_audit_rows_carry_actor_and_stats_shape(
        self, migrated: psycopg.Connection, tmp_path: Path
    ) -> None:
        from faers_signal_pipeline.pipeline import load_quarter

        zip_path = build_quarter_zip(tmp_path / "q.zip", QUARTER)
        load_quarter(migrated, zip_path, QUARTER, report_dir=tmp_path / "reports")
        with migrated.cursor() as cur:
            cur.execute(
                "SELECT actor, object, details FROM audit_log"
                " WHERE action = 'stage_quarter' ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
        assert row is not None
        actor, obj, details = row
        assert actor  # current_user, never blank
        assert obj == "runs"
        assert "run_id" in details
