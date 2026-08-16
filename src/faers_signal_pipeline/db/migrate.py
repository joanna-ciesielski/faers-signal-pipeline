"""Plain-SQL migration runner.

Design (see migrations/README.md):

- Numbered ``NNNN_name.sql`` files applied in order, tracked in
  ``schema_migrations`` with a SHA-256 of the file content.
- Applied history is immutable: an edited already-applied file, or a
  tracking row with no matching file, refuses to proceed (drift error) —
  schema changes are always new files.
- Idempotent and cheap when up to date; every pipeline stage calls it
  defensively, preserving the "fresh clone just works" behavior.
- Safe under concurrency: a per-schema advisory lock serializes appliers
  (two quarters loading in parallel race to create tables otherwise).
- Applies into the FIRST schema of the caller's ``search_path``, so the
  per-schema test databases exercise the exact production DDL.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


class MigrationDriftError(RuntimeError):
    """Applied history and migration files disagree; refuse to guess."""


@dataclass(frozen=True, slots=True)
class MigrationFile:
    version: int
    name: str
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class MigrationReport:
    total_migrations: int
    newly_applied: int


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[MigrationFile]:
    files: list[MigrationFile] = []
    for path in sorted(directory.glob("*.sql")):
        prefix, _, rest = path.stem.partition("_")
        files.append(
            MigrationFile(
                version=int(prefix),
                name=rest,
                path=path,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return files


_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    integer     PRIMARY KEY,
    name       text        NOT NULL,
    sha256     text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def apply_migrations(conn: psycopg.Connection) -> MigrationReport:
    """Apply pending migrations; verify already-applied ones; idempotent."""
    files = migration_files()
    newly_applied = 0
    with conn.cursor() as cur, conn.transaction():
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema(), 0))")
        cur.execute(_TRACKING_DDL)
        cur.execute("SELECT version, sha256 FROM schema_migrations")
        applied: dict[int, str] = {row[0]: row[1] for row in cur.fetchall()}
        phantom = sorted(set(applied) - {f.version for f in files})
        if phantom:
            msg = f"schema_migrations lists versions with no matching file: {phantom}"
            raise MigrationDriftError(msg)
        for migration in files:
            filename = f"{migration.version:04d}_{migration.name}.sql"
            if migration.version in applied:
                if applied[migration.version] != migration.sha256:
                    msg = (
                        f"{filename} changed after being applied (checksum"
                        " mismatch); applied history is immutable — write a"
                        " new migration instead"
                    )
                    raise MigrationDriftError(msg)
                continue
            cur.execute(migration.path.read_text(encoding="utf-8"))
            cur.execute(
                "INSERT INTO schema_migrations (version, name, sha256) VALUES (%s, %s, %s)",
                (migration.version, migration.name, migration.sha256),
            )
            newly_applied += 1
    return MigrationReport(total_migrations=len(files), newly_applied=newly_applied)
