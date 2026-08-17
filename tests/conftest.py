"""Shared fixtures: synthetic FAERS quarterly zips (no real data needed).

The synthetic archive mirrors the documented structure of a current-era
quarter: ``ASCII/<TABLE>yyQq.txt`` ($-delimited, header row) plus
``ASC_NTS.pdf`` and ``README.pdf`` placeholders. All content is invented;
nothing is derived from real FAERS reports.

This module also enforces the offline invariant: the autouse guard below
blocks socket connections to anything but loopback for every test, so an
accidental live-network dependency fails loudly rather than passing green
on a connected machine and flaking in CI.
"""

from __future__ import annotations

import os
import socket
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from faers_signal_pipeline.layout import DELIMITER, tables_for_era
from faers_signal_pipeline.quarter import Quarter

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def database_url() -> str:
    """Resolve the test database DSN (localhost only, per the socket guard).

    Priority: explicit ``DATABASE_URL`` env (CI service container), else the
    repo's ``.env`` (docker compose values) — so a fresh clone's
    ``docker compose up`` + ``uv run pytest`` just works. Returns "" when
    neither is available; DB tests then skip.
    """
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return ""
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    password = values.get("POSTGRES_PASSWORD", "")
    if not password:
        return ""
    user = quote(values.get("POSTGRES_USER", "faers"), safe="")
    database = values.get("POSTGRES_DB", "faers")
    port = values.get("POSTGRES_PORT", "5432")
    # Passwords may contain URL-special characters (@, /, :) — encode them.
    return f"postgresql://{user}:{quote(password, safe='')}@127.0.0.1:{port}/{database}"


@pytest.fixture(autouse=True)
def _no_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block non-loopback socket connections for the duration of every test."""
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> None:
        # AF_INET/AF_INET6 addresses are tuples whose first element is the
        # host; AF_UNIX addresses are path strings and stay allowed.
        if (
            isinstance(address, tuple)
            and address
            and isinstance(address[0], str)
            and address[0] not in _LOOPBACK_HOSTS
        ):
            msg = f"test attempted external network access to {address[0]!r}"
            raise RuntimeError(msg)
        real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


def build_quarter_zip(
    destination: Path,
    quarter: Quarter,
    *,
    omit_tables: frozenset[str] = frozenset(),
    header_overrides: dict[str, str] | None = None,
    data_rows: dict[str, list[str]] | None = None,
    include_docs: bool = True,
    include_deleted: bool = True,
    deleted_lines: list[str] | None = None,
    subdir: str = "ASCII",
    doc_names: tuple[str, ...] = ("ASC_NTS.pdf", "README.pdf"),
) -> Path:
    """Write a synthetic quarterly archive shaped like the real thing.

    ``data_rows`` supplies raw $-delimited data lines per table (appended
    after the header). ``deleted_lines`` supplies raw deleted-list lines;
    the default mirrors the real format (leading blank line, bare CASEIDs).
    """
    header_overrides = header_overrides or {}
    data_rows = data_rows or {}
    suffix = quarter.table_file_stem_suffix
    with zipfile.ZipFile(destination, "w") as archive:
        if include_docs:
            for doc_name in doc_names:
                archive.writestr(doc_name, b"placeholder documentation")
        if include_deleted:
            lines = deleted_lines if deleted_lines is not None else [" "]
            archive.writestr(
                f"Deleted/{quarter.deleted_file_name}",
                ("\n".join(lines) + "\n").encode("latin-1"),
            )
        for table, spec in tables_for_era(quarter.era).items():
            if table in omit_tables:
                continue
            header = header_overrides.get(table, DELIMITER.join(spec.columns).upper())
            member = (
                f"{subdir}/{table.upper()}{suffix}.txt"
                if subdir
                else (f"{table.upper()}{suffix}.txt")
            )
            body = "\r\n".join([header, *data_rows.get(table, [])])
            # Real FAERS files are latin-1/ASCII, not UTF-8: encode explicitly
            # so 8-bit test bytes reach the parser exactly as they would from
            # a real quarter.
            archive.writestr(member, (body + "\r\n").encode("latin-1"))
    return destination


@pytest.fixture
def quarter_2026q2() -> Quarter:
    return Quarter(2026, 2)


@pytest.fixture
def good_zip(tmp_path: Path, quarter_2026q2: Quarter) -> Path:
    return build_quarter_zip(tmp_path / "faers_ascii_2026q2.zip", quarter_2026q2)
