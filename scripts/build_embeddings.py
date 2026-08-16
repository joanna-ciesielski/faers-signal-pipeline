"""CLI: build deterministic drug-profile texts and embed them.

Usage:
    uv run python scripts/build_embeddings.py                # real model
    uv run python scripts/build_embeddings.py --embedder stub

Requires DATABASE_URL. The real embedder needs the optional extra
(`uv sync --extra vectors`); first use downloads model weights once (an
explicit network event — tests never take this path). Re-runs embed only
profiles whose text or model changed: an unchanged database proves
itself with `embedded: 0`.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg

from faers_signal_pipeline.signals.profiles import build_profiles
from faers_signal_pipeline.vectors.embed import (
    BgeSmallEmbedder,
    Embedder,
    HashEmbedder,
    embed_profiles,
)


def make_embedder(kind: str) -> Embedder:
    if kind == "stub":
        return HashEmbedder()
    return BgeSmallEmbedder()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedder", choices=["bge", "stub"], default="bge")
    parser.add_argument("--batch-size", type=int, default=64)
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
        built = build_profiles(conn)
        outcome = embed_profiles(conn, embedder, batch_size=args.batch_size)
    print(
        f"profiles: cutoff={built.cutoff_quarter}"
        f" built={built.profiles_built} removed={built.profiles_removed}"
    )
    print(
        f"embeddings: model={outcome.model}"
        f" embedded={outcome.embedded} up_to_date={outcome.up_to_date}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
