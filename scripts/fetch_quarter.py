"""CLI: download + checksum + layout-verify one FAERS quarter into the cache.

Usage:
    uv run python scripts/fetch_quarter.py 2026q2 [--cache-dir data/faers-cache]

Exit codes:
    0  fetched (or cache hit) and layout verified
    1  fetched but layout verification failed (see manifest for reason codes)
    2  download failed / bad arguments
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import httpx

from faers_signal_pipeline.fetch import DEFAULT_BASE_URL, FetchError, fetch_quarter
from faers_signal_pipeline.quarter import Quarter, QuarterFormatError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quarter", help="quarter to fetch, e.g. 2026q2")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.environ.get("FAERS_CACHE_DIR", "data/faers-cache")),
        help="cache directory (default: $FAERS_CACHE_DIR or data/faers-cache)",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="override download base URL")
    args = parser.parse_args(argv)

    try:
        quarter = Quarter.parse(args.quarter)
    except QuarterFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
            result = fetch_quarter(
                quarter, cache_dir=args.cache_dir, client=client, base_url=args.base_url
            )
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    origin = "cache" if result.from_cache else "download"
    print(f"{quarter.label}: {origin} -> {result.zip_path}")
    print(f"  sha256: {result.sha256}")
    print(f"  size:   {result.size_bytes} bytes")
    print(f"  manifest: {result.manifest_path}")
    if result.verification.ok:
        print("  layout: verified")
        return 0
    print("  layout: FAILED verification", file=sys.stderr)
    for finding in result.verification.findings:
        print(f"    {json.dumps(asdict(finding))}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
