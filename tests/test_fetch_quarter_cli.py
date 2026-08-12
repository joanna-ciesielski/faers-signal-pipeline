"""CLI exit-code contract for scripts/fetch_quarter.py.

The success/failure paths run against a pre-populated cache (cache hits make
zero network calls), so the whole suite stays offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import build_quarter_zip
from tests.test_fetch import BASE_URL, make_client

from faers_signal_pipeline.fetch import fetch_quarter, sha256_of
from faers_signal_pipeline.quarter import Quarter
from fetch_quarter import main


def test_malformed_quarter_exits_2() -> None:
    assert main(["not-a-quarter"]) == 2


def test_unreachable_base_url_exits_2(tmp_path: Path) -> None:
    # 127.0.0.1:9 with nothing listening refuses immediately; stays offline.
    exit_code = main(
        ["2026q2", "--cache-dir", str(tmp_path), "--base-url", "http://127.0.0.1:9/Exports"]
    )
    assert exit_code == 2


def test_verified_cache_hit_exits_0(
    tmp_path: Path, quarter_2026q2: Quarter, good_zip: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = tmp_path / "cache"
    url = f"{BASE_URL}/faers_ascii_2026q2.zip"
    with make_client({url: good_zip.read_bytes()}) as client:
        fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

    exit_code = main(["2026q2", "--cache-dir", str(cache), "--base-url", BASE_URL])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "cache" in out
    assert "layout: verified" in out


def test_cached_but_layout_broken_exits_1(
    tmp_path: Path, quarter_2026q2: Quarter, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    zip_path = cache / "faers_ascii_2026q2.zip"
    build_quarter_zip(zip_path, quarter_2026q2, omit_tables=frozenset({"demo"}))
    manifest = {
        "manifest_version": 1,
        "quarter": "2026q2",
        "url": None,
        "sha256": sha256_of(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "verification": {},
    }
    zip_path.with_suffix(".manifest.json").write_text(json.dumps(manifest))

    exit_code = main(["2026q2", "--cache-dir", str(cache), "--base-url", BASE_URL])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "table_file_missing" in err
