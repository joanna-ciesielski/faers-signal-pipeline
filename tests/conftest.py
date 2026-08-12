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

import socket
import zipfile
from pathlib import Path
from typing import Any

import pytest

from faers_signal_pipeline.layout import DELIMITER, FAERS_2014Q3_TABLES
from faers_signal_pipeline.quarter import Quarter

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


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
    include_docs: bool = True,
    subdir: str = "ASCII",
) -> Path:
    """Write a synthetic quarterly archive shaped like the real thing."""
    header_overrides = header_overrides or {}
    suffix = quarter.table_file_stem_suffix
    with zipfile.ZipFile(destination, "w") as archive:
        if include_docs:
            archive.writestr("ASC_NTS.pdf", b"placeholder documentation")
            archive.writestr("README.pdf", b"placeholder readme")
        for table, spec in FAERS_2014Q3_TABLES.items():
            if table in omit_tables:
                continue
            header = header_overrides.get(table, DELIMITER.join(spec.columns).upper())
            member = (
                f"{subdir}/{table.upper()}{suffix}.txt"
                if subdir
                else (f"{table.upper()}{suffix}.txt")
            )
            archive.writestr(member, header + "\r\n")
    return destination


@pytest.fixture
def quarter_2026q2() -> Quarter:
    return Quarter(2026, 2)


@pytest.fixture
def good_zip(tmp_path: Path, quarter_2026q2: Quarter) -> Path:
    return build_quarter_zip(tmp_path / "faers_ascii_2026q2.zip", quarter_2026q2)
