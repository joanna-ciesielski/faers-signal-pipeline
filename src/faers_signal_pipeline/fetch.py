"""Download, checksum, cache, and layout-verify a FAERS quarterly extract.

Behavior contract:

- Cached-and-verified quarters are never re-downloaded; a cache hit performs
  zero network calls (asserted in tests — determinism starts here).
- Every outcome is recorded in a machine-readable JSON manifest next to the
  zip: url used, SHA-256, byte size, verification findings.
- Verification failures never delete or truncate data; the artifact stays on
  disk, marked failed, with reason codes (mirrors the quarantine philosophy:
  nothing is silently dropped).
"""

from __future__ import annotations

import enum
import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from faers_signal_pipeline.layout import DELIMITER, TableSpec, tables_for_era
from faers_signal_pipeline.quarter import Quarter

DEFAULT_BASE_URL = "https://fis.fda.gov/content/Exports"
_CHUNK_SIZE = 1 << 20  # 1 MiB
MANIFEST_VERSION = 1


class VerificationCode(enum.StrEnum):
    """Machine-readable verification reason codes."""

    OK = "ok"
    ZIP_UNREADABLE = "zip_unreadable"
    TABLE_FILE_MISSING = "table_file_missing"
    TABLE_FILE_AMBIGUOUS = "table_file_ambiguous"
    HEADER_MISMATCH = "header_mismatch"
    HEADER_UNREADABLE = "header_unreadable"
    README_MISSING = "readme_missing"
    ERA_UNSUPPORTED = "era_unsupported"


@dataclass(frozen=True, slots=True)
class Finding:
    """One verification finding for one table (or the archive as a whole)."""

    code: VerificationCode
    table: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Outcome of layout verification for one downloaded quarter."""

    quarter: str
    era: str
    ok: bool
    findings: tuple[Finding, ...]
    table_members: dict[str, str] = field(default_factory=dict)
    doc_members: tuple[str, ...] = ()


class FetchError(RuntimeError):
    """The quarter could not be downloaded from any candidate URL."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_header(raw_header: str, spec: TableSpec) -> tuple[str, ...]:
    columns = [column.strip().lower() for column in raw_header.rstrip("\r\n").split(DELIMITER)]
    return tuple(spec.aliases.get(column, column) for column in columns)


def _locate_members(names: list[str], quarter: Quarter) -> tuple[dict[str, list[str]], list[str]]:
    """Split archive members into candidate table files and doc files."""
    suffix = quarter.table_file_stem_suffix.lower()
    tables: dict[str, list[str]] = {}
    docs: list[str] = []
    for name in names:
        stem = Path(name).name.lower()
        if not stem:
            continue
        if stem.startswith(("asc_nts", "readme")):
            docs.append(name)
            continue
        for table in ("demo", "drug", "reac", "outc", "rpsr", "ther", "indi"):
            if stem == f"{table}{suffix}.txt":
                tables.setdefault(table, []).append(name)
    return tables, docs


def verify_layout(zip_path: Path, quarter: Quarter) -> VerificationReport:
    """Verify a downloaded quarter's archive against its era's layout spec.

    Checks: archive readability, presence of each expected table file and of
    the README/ASC_NTS documentation, and each table's header row against the
    era's expected column order (accepting documented aliases).
    """
    findings: list[Finding] = []
    table_members: dict[str, str] = {}
    doc_members: tuple[str, ...] = ()

    try:
        specs = tables_for_era(quarter.era)
    except NotImplementedError as exc:
        findings.append(Finding(code=VerificationCode.ERA_UNSUPPORTED, detail=str(exc)))
        return VerificationReport(
            quarter=quarter.label, era=quarter.era.value, ok=False, findings=tuple(findings)
        )

    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            candidates, docs = _locate_members(names, quarter)
            doc_members = tuple(sorted(docs))
            if not docs:
                findings.append(
                    Finding(
                        code=VerificationCode.README_MISSING,
                        detail="no ASC_NTS/README member found in archive",
                    )
                )
            for table, spec in specs.items():
                members = candidates.get(table, [])
                if not members:
                    findings.append(
                        Finding(
                            code=VerificationCode.TABLE_FILE_MISSING,
                            table=table,
                            detail=f"expected member {table.upper()}"
                            f"{quarter.table_file_stem_suffix}.txt",
                        )
                    )
                    continue
                if len(members) > 1:
                    findings.append(
                        Finding(
                            code=VerificationCode.TABLE_FILE_AMBIGUOUS,
                            table=table,
                            detail=f"multiple candidates: {sorted(members)}",
                        )
                    )
                    continue
                member = members[0]
                table_members[table] = member
                findings.extend(_verify_header(archive, member, table, spec))
    except (OSError, zipfile.BadZipFile) as exc:
        findings.append(Finding(code=VerificationCode.ZIP_UNREADABLE, detail=str(exc)))

    ok = not findings
    if ok:
        findings.append(Finding(code=VerificationCode.OK))
    return VerificationReport(
        quarter=quarter.label,
        era=quarter.era.value,
        ok=ok,
        findings=tuple(findings),
        table_members=table_members,
        doc_members=doc_members,
    )


def _verify_header(
    archive: zipfile.ZipFile, member: str, table: str, spec: TableSpec
) -> list[Finding]:
    try:
        with archive.open(member) as handle:
            raw = handle.readline(1 << 16).decode("latin-1")
    except (OSError, zipfile.BadZipFile) as exc:
        return [Finding(code=VerificationCode.HEADER_UNREADABLE, table=table, detail=str(exc))]
    header = _normalize_header(raw, spec)
    if header != spec.columns:
        return [
            Finding(
                code=VerificationCode.HEADER_MISMATCH,
                table=table,
                detail=f"expected {list(spec.columns)}, found {list(header)}",
            )
        ]
    return []


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of fetch_quarter: paths plus provenance."""

    zip_path: Path
    manifest_path: Path
    sha256: str
    size_bytes: int
    from_cache: bool
    url: str | None
    verification: VerificationReport


def _manifest_path(zip_path: Path) -> Path:
    return zip_path.with_suffix(".manifest.json")


def _write_manifest(path: Path, result: FetchResult) -> None:
    payload = {
        "manifest_version": MANIFEST_VERSION,
        "quarter": result.verification.quarter,
        "url": result.url,
        "sha256": result.sha256,
        "size_bytes": result.size_bytes,
        "verification": asdict(result.verification),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_cached(zip_path: Path, quarter: Quarter) -> FetchResult | None:
    manifest_path = _manifest_path(zip_path)
    if not (zip_path.exists() and manifest_path.exists()):
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    recorded_sha = manifest.get("sha256")
    if not isinstance(recorded_sha, str) or sha256_of(zip_path) != recorded_sha:
        return None
    verification = verify_layout(zip_path, quarter)
    result = FetchResult(
        zip_path=zip_path,
        manifest_path=manifest_path,
        sha256=recorded_sha,
        size_bytes=zip_path.stat().st_size,
        from_cache=True,
        url=manifest.get("url"),
        verification=verification,
    )
    _write_manifest(manifest_path, result)
    return result


def fetch_quarter(
    quarter: Quarter,
    cache_dir: Path,
    client: httpx.Client,
    base_url: str = DEFAULT_BASE_URL,
) -> FetchResult:
    """Fetch one quarter's ASCII zip into the cache and verify its layout.

    A verified cache hit performs zero network calls. On download, candidate
    URLs are tried in order (FDA's casing is inconsistent); the first success
    wins and is recorded in the manifest.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / f"faers_ascii_{quarter.label}.zip"

    cached = _load_cached(zip_path, quarter)
    if cached is not None:
        return cached

    errors: list[str] = []
    for url in quarter.zip_url_candidates(base_url):
        try:
            _download(client, url, zip_path)
        except (httpx.HTTPError, FetchError) as exc:
            errors.append(f"{url}: {exc}")
            continue
        verification = verify_layout(zip_path, quarter)
        result = FetchResult(
            zip_path=zip_path,
            manifest_path=_manifest_path(zip_path),
            sha256=sha256_of(zip_path),
            size_bytes=zip_path.stat().st_size,
            from_cache=False,
            url=url,
            verification=verification,
        )
        _write_manifest(result.manifest_path, result)
        return result

    msg = "all candidate URLs failed: " + "; ".join(errors)
    raise FetchError(msg)


def _download(client: httpx.Client, url: str, destination: Path) -> None:
    partial = destination.with_suffix(".partial")
    try:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                msg = f"HTTP {response.status_code}"
                raise FetchError(msg)
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    handle.write(chunk)
    except BaseException:
        partial.unlink(missing_ok=True)  # never leave a truncated artifact behind
        raise
    partial.replace(destination)
