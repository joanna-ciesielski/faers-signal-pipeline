"""CLI: hybrid semantic search over drug safety profiles.

Usage:
    uv run python scripts/semantic_search.py "progestogen meningioma risk"
    uv run python scripts/semantic_search.py "hair loss" --must-contain Alopecia
    uv run python scripts/semantic_search.py "anything" --embedder stub

Requires DATABASE_URL and previously built embeddings
(scripts/build_embeddings.py). The query is embedded with the SAME model
that embedded the profiles — mixing models yields garbage distances, so
pick the embedder you built with.

Research and monitoring tool: spontaneous reports, no denominators —
signal detection, not risk quantification. Not medical advice.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg

from faers_signal_pipeline.vectors.embed import (
    BgeSmallEmbedder,
    Embedder,
    HashEmbedder,
    semantic_search,
)


def make_embedder(kind: str) -> Embedder:
    if kind == "stub":
        return HashEmbedder()
    return BgeSmallEmbedder()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--must-contain", default=None)
    parser.add_argument("--embedder", choices=["bge", "stub"], default="bge")
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("error: DATABASE_URL must be set", file=sys.stderr)
        return 2
    try:
        embedder = make_embedder(args.embedder)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with psycopg.connect(database_url) as conn:
        conn.autocommit = True
        hits = semantic_search(conn, embedder, args.query, k=args.k, must_contain=args.must_contain)
    if not hits:
        print("no results (build embeddings first?)")
        return 1
    for rank, hit in enumerate(hits, start=1):
        print(
            f"{rank:2d}. {hit.display_name}  rxcui={hit.rxcui}"
            f"  distance={hit.distance:.6f}  cutoff={hit.cutoff_quarter}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
