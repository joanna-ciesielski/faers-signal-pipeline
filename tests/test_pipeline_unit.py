"""DB-free unit tests for pipeline helpers and CLI precondition paths."""

from __future__ import annotations

import json
from pathlib import Path

from faers_signal_pipeline.pipeline import _read_manifest_sha
from load_quarter import main


class TestReadManifestSha:
    def test_missing_manifest_returns_none(self, tmp_path: Path) -> None:
        assert _read_manifest_sha(tmp_path / "nope.zip") is None

    def test_corrupt_manifest_returns_none(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "q.zip"
        zip_path.with_suffix(".manifest.json").write_text("{broken")
        assert _read_manifest_sha(zip_path) is None

    def test_non_string_sha_returns_none(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "q.zip"
        zip_path.with_suffix(".manifest.json").write_text(json.dumps({"sha256": 42}))
        assert _read_manifest_sha(zip_path) is None

    def test_valid_sha_returned(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "q.zip"
        zip_path.with_suffix(".manifest.json").write_text(json.dumps({"sha256": "abc"}))
        assert _read_manifest_sha(zip_path) == "abc"


class TestLoadQuarterCliPreconditions:
    def test_bad_quarter_exits_2(self) -> None:
        assert main(["nope"]) == 2

    def test_missing_database_url_exits_2(self, tmp_path: Path) -> None:
        assert main(["2026q2", "--cache-dir", str(tmp_path), "--database-url", ""]) == 2

    def test_missing_zip_exits_2(self, tmp_path: Path) -> None:
        assert (
            main(
                [
                    "2026q2",
                    "--cache-dir",
                    str(tmp_path),
                    "--database-url",
                    "postgresql://nobody@127.0.0.1:5432/nope",
                ]
            )
            == 2
        )
