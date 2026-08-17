"""Fetch, checksum, cache, and layout-verification behavior — fully offline.

Network is simulated with httpx.MockTransport. The cache-hit test asserts
zero network calls: determinism and offline re-runs are project invariants,
gated from Phase 0 onward.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from tests.conftest import build_quarter_zip

from faers_signal_pipeline.fetch import (
    FetchError,
    VerificationCode,
    fetch_quarter,
    sha256_of,
    verify_layout,
)
from faers_signal_pipeline.quarter import Quarter

BASE_URL = "https://example.test/Exports"


def make_client(payloads: dict[str, bytes], calls: list[str] | None = None) -> httpx.Client:
    """Client serving byte payloads by exact URL; 404 otherwise."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if url in payloads:
            return httpx.Response(200, content=payloads[url])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def zip_bytes(good_zip: Path) -> bytes:
    return good_zip.read_bytes()


class TestDownload:
    def test_downloads_checksums_and_verifies(
        self, tmp_path: Path, quarter_2026q2: Quarter, zip_bytes: bytes
    ) -> None:
        cache = tmp_path / "cache"
        url = f"{BASE_URL}/faers_ascii_2026q2.zip"
        with make_client({url: zip_bytes}) as client:
            result = fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

        assert result.from_cache is False
        assert result.url == url
        assert result.zip_path.read_bytes() == zip_bytes
        assert result.sha256 == sha256_of(result.zip_path)
        assert result.size_bytes == len(zip_bytes)
        assert result.verification.ok

        manifest = json.loads(result.manifest_path.read_text())
        assert manifest["sha256"] == result.sha256
        assert manifest["url"] == url
        assert manifest["verification"]["ok"] is True

    def test_falls_back_to_uppercase_q_url(
        self, tmp_path: Path, quarter_2026q2: Quarter, zip_bytes: bytes
    ) -> None:
        upper_url = f"{BASE_URL}/faers_ascii_2026Q2.zip"
        with make_client({upper_url: zip_bytes}) as client:
            result = fetch_quarter(quarter_2026q2, tmp_path / "cache", client, base_url=BASE_URL)
        assert result.url == upper_url
        assert result.verification.ok

    def test_all_urls_failing_raises_with_details(
        self, tmp_path: Path, quarter_2026q2: Quarter
    ) -> None:
        with make_client({}) as client, pytest.raises(FetchError, match="404"):
            fetch_quarter(quarter_2026q2, tmp_path / "cache", client, base_url=BASE_URL)

    def test_failed_download_leaves_no_zip_artifact(
        self, tmp_path: Path, quarter_2026q2: Quarter
    ) -> None:
        cache = tmp_path / "cache"
        with make_client({}) as client, pytest.raises(FetchError):
            fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)
        assert not (cache / "faers_ascii_2026q2.zip").exists()


class TestCache:
    def test_cache_hit_makes_zero_network_calls(
        self, tmp_path: Path, quarter_2026q2: Quarter, zip_bytes: bytes
    ) -> None:
        cache = tmp_path / "cache"
        url = f"{BASE_URL}/faers_ascii_2026q2.zip"
        with make_client({url: zip_bytes}) as client:
            fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

        calls: list[str] = []
        with make_client({url: zip_bytes}, calls=calls) as client:
            result = fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

        assert result.from_cache is True
        assert calls == []  # the invariant: cached quarter -> no network
        assert result.verification.ok

    def test_corrupted_cache_triggers_redownload(
        self, tmp_path: Path, quarter_2026q2: Quarter, zip_bytes: bytes
    ) -> None:
        cache = tmp_path / "cache"
        url = f"{BASE_URL}/faers_ascii_2026q2.zip"
        with make_client({url: zip_bytes}) as client:
            first = fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

        first.zip_path.write_bytes(b"corrupted")

        calls: list[str] = []
        with make_client({url: zip_bytes}, calls=calls) as client:
            second = fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

        assert second.from_cache is False
        assert calls  # network was used to repair the cache
        assert second.verification.ok

    def test_corrupt_manifest_triggers_redownload(
        self, tmp_path: Path, quarter_2026q2: Quarter, zip_bytes: bytes
    ) -> None:
        cache = tmp_path / "cache"
        url = f"{BASE_URL}/faers_ascii_2026q2.zip"
        with make_client({url: zip_bytes}) as client:
            first = fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

        first.manifest_path.write_text("{not json")

        calls: list[str] = []
        with make_client({url: zip_bytes}, calls=calls) as client:
            second = fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

        assert second.from_cache is False
        assert calls
        # The repaired manifest is valid again.
        assert json.loads(second.manifest_path.read_text())["sha256"] == second.sha256

    def test_mid_stream_failure_leaves_no_partial_artifact(
        self, tmp_path: Path, quarter_2026q2: Quarter
    ) -> None:
        cache = tmp_path / "cache"

        def dropping_body() -> Iterator[bytes]:
            yield b"first chunk arrives fine"
            raise httpx.ReadError("connection dropped mid-stream")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=dropping_body())

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            pytest.raises(FetchError, match="mid-stream"),
        ):
            fetch_quarter(quarter_2026q2, cache, client, base_url=BASE_URL)

        assert list(cache.iterdir()) == []  # no zip, no .partial, no manifest


class TestVerifyLayout:
    def test_good_archive_passes_with_single_ok_finding(
        self, good_zip: Path, quarter_2026q2: Quarter
    ) -> None:
        report = verify_layout(good_zip, quarter_2026q2)
        assert report.ok
        assert [f.code for f in report.findings] == [VerificationCode.OK]
        assert set(report.table_members) == {
            "demo",
            "drug",
            "reac",
            "outc",
            "rpsr",
            "ther",
            "indi",
        }
        assert report.doc_members  # ASC_NTS/README seen

    def test_missing_table_file_reported(self, tmp_path: Path, quarter_2026q2: Quarter) -> None:
        path = build_quarter_zip(
            tmp_path / "missing.zip", quarter_2026q2, omit_tables=frozenset({"reac"})
        )
        report = verify_layout(path, quarter_2026q2)
        assert not report.ok
        assert any(
            f.code is VerificationCode.TABLE_FILE_MISSING and f.table == "reac"
            for f in report.findings
        )

    def test_header_mismatch_reported_with_detail(
        self, tmp_path: Path, quarter_2026q2: Quarter
    ) -> None:
        path = build_quarter_zip(
            tmp_path / "drifted.zip",
            quarter_2026q2,
            header_overrides={"outc": "PRIMARYID$CASEID$OUTC_COD$SURPRISE_COL"},
        )
        report = verify_layout(path, quarter_2026q2)
        assert not report.ok
        [finding] = [f for f in report.findings if f.code is VerificationCode.HEADER_MISMATCH]
        assert finding.table == "outc"
        assert "surprise_col" in finding.detail

    def test_gndr_cod_alias_accepted_for_demo(
        self, tmp_path: Path, quarter_2026q2: Quarter
    ) -> None:
        from faers_signal_pipeline.layout import FAERS_2014Q3_TABLES

        legacy_header = "$".join(
            "GNDR_COD" if col == "sex" else col.upper()
            for col in FAERS_2014Q3_TABLES["demo"].columns
        )
        path = build_quarter_zip(
            tmp_path / "aliased.zip", quarter_2026q2, header_overrides={"demo": legacy_header}
        )
        report = verify_layout(path, quarter_2026q2)
        assert report.ok

    def test_missing_docs_reported(self, tmp_path: Path, quarter_2026q2: Quarter) -> None:
        path = build_quarter_zip(tmp_path / "nodocs.zip", quarter_2026q2, include_docs=False)
        report = verify_layout(path, quarter_2026q2)
        assert not report.ok
        assert any(f.code is VerificationCode.README_MISSING for f in report.findings)

    def test_flat_archive_without_subdir_still_verifies(
        self, tmp_path: Path, quarter_2026q2: Quarter
    ) -> None:
        # Packaging drift: table files at archive root instead of ASCII/.
        path = build_quarter_zip(tmp_path / "flat.zip", quarter_2026q2, subdir="")
        report = verify_layout(path, quarter_2026q2)
        assert report.ok

    def test_deleted_member_recorded(self, good_zip: Path, quarter_2026q2: Quarter) -> None:
        report = verify_layout(good_zip, quarter_2026q2)
        assert report.deleted_member == "Deleted/DELETE26Q2.txt"

    def test_missing_deleted_list_is_nonfatal_info_finding(
        self, tmp_path: Path, quarter_2026q2: Quarter
    ) -> None:
        # Older eras may predate the Deleted/ folder: absence is recorded but
        # does not fail verification; the *load* step requires an explicit
        # override (see pipeline tests).
        path = build_quarter_zip(tmp_path / "nodeleted.zip", quarter_2026q2, include_deleted=False)
        report = verify_layout(path, quarter_2026q2)
        assert report.ok
        assert report.deleted_member is None
        [finding] = [f for f in report.findings if f.code is VerificationCode.DELETED_LIST_MISSING]
        assert finding.severity == "info"

    def test_unreadable_zip_reported(self, tmp_path: Path, quarter_2026q2: Quarter) -> None:
        path = tmp_path / "bad.zip"
        path.write_bytes(b"this is not a zip")
        report = verify_layout(path, quarter_2026q2)
        assert not report.ok
        assert any(f.code is VerificationCode.ZIP_UNREADABLE for f in report.findings)

    def test_unreadable_legacy_archive_reported(self, tmp_path: Path) -> None:
        """Graduated in Phase 8b: every era now has a spec, so a legacy
        quarter proceeds to real verification — an unreadable file reports
        ZIP_UNREADABLE rather than ERA_UNSUPPORTED."""
        early = Quarter(2010, 1)
        path = tmp_path / "early.zip"
        path.write_bytes(b"irrelevant")
        report = verify_layout(path, early)
        assert not report.ok
        assert [f.code for f in report.findings] == [VerificationCode.ZIP_UNREADABLE]
