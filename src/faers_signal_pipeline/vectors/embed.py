"""Embedding bookkeeping and semantic search over drug profiles.

Two embedders share one small protocol:

- ``HashEmbedder`` — deterministic, offline, dependency-free. Tests and
  CI use it exclusively (the offline invariant is socket-enforced).
- ``BgeSmallEmbedder`` — the real model (BAAI/bge-small-en-v1.5, 384-d,
  cosine) behind the optional ``vectors`` dependency extra. Loading it
  downloads model weights ONCE (an explicit, cached network event on the
  maintainer machine — never in tests).

Bookkeeping mirrors the RxNav mapper's cache-first discipline: a profile
is re-embedded only when its ``profile_sha256`` no longer matches the
``embedded_sha`` recorded at embed time, or when the model name changes.
Unchanged state => zero embedding work, provable by re-running.

All SQL is search_path-proof: the vector type/operators live in the
``public`` schema (see 0007_vectors.sql) and are referenced qualified.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Any, Protocol

import psycopg

#: bge-small-en-v1.5 output dimension; the stub matches it so the same
#: column serves both.
EMBEDDING_DIM = 384

DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic pseudo-embeddings from SHAKE-256; unit-norm.

    Carries no semantics — it exists so bookkeeping, storage, indexing,
    and ranking are testable offline and reproducibly. Identical text =>
    identical vector; distance-to-self == 0 is the invariant tests use.
    """

    def __init__(self, model_name: str = "stub-shake256-v1") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            raw = hashlib.shake_256(f"{self._model_name}\x00{text}".encode()).digest(
                EMBEDDING_DIM * 4
            )
            ints = struct.unpack(f"<{EMBEDDING_DIM}I", raw)
            floats = [(value / 2**31) - 1.0 for value in ints]
            norm = sum(component * component for component in floats) ** 0.5
            vectors.append([component / norm for component in floats])
        return vectors


class BgeSmallEmbedder:
    """bge-small-en-v1.5 via sentence-transformers (optional extra).

    Import and model load are lazy so the base install never needs torch.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised only sans extra
            msg = (
                "sentence-transformers is not installed; install the extra: uv sync --extra vectors"
            )
            raise RuntimeError(msg) from exc
        self._model_name = model_name
        self._model: Any = SentenceTransformer(model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        encoded = self._model.encode(texts, normalize_embeddings=True)
        return [[float(component) for component in row] for row in encoded]


@dataclass(frozen=True, slots=True)
class EmbedOutcome:
    model: str
    embedded: int
    up_to_date: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    rxcui: str
    display_name: str
    distance: float
    cutoff_quarter: str


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(component) for component in vector) + "]"


def embed_profiles(
    conn: psycopg.Connection, embedder: Embedder, batch_size: int = 64
) -> EmbedOutcome:
    """Embed profiles whose text or model changed since the last embed."""
    total_row = conn.execute("SELECT count(*) FROM drug_profiles").fetchone()
    total = int(total_row[0]) if total_row is not None else 0
    pending = conn.execute(
        "SELECT cutoff_quarter, rxcui, profile_text, profile_sha256 FROM drug_profiles"
        " WHERE embedding IS NULL"
        " OR embedded_sha IS DISTINCT FROM profile_sha256"
        " OR model IS DISTINCT FROM %s"
        " ORDER BY cutoff_quarter, rxcui",
        (embedder.model_name,),
    ).fetchall()
    embedded = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = embedder.embed([str(row[2]) for row in batch])
        with conn.cursor() as cur, conn.transaction():
            for (cutoff, rxcui, _text, sha), vector in zip(batch, vectors, strict=True):
                cur.execute(
                    "UPDATE drug_profiles SET"
                    " embedding = CAST(%s AS public.vector),"
                    " embedded_sha = %s, model = %s, embedded_at = now()"
                    " WHERE cutoff_quarter = %s AND rxcui = %s",
                    (_vector_literal(vector), sha, embedder.model_name, cutoff, rxcui),
                )
                embedded += 1
    return EmbedOutcome(
        model=embedder.model_name, embedded=embedded, up_to_date=total - len(pending)
    )


def semantic_search(
    conn: psycopg.Connection,
    embedder: Embedder,
    query: str,
    k: int = 10,
    must_contain: str | None = None,
) -> list[SearchHit]:
    """Nearest profiles by cosine distance; optional lexical filter.

    Ordering is fully deterministic: (distance ASC, rxcui ASC). The
    ``must_contain`` filter is the "hybrid" part — a plain case-insensitive
    substring match on the profile text (e.g. a reaction term as
    published), applied before ranking.
    """
    [query_vector] = embedder.embed([query])
    if must_contain is not None:
        rows = conn.execute(
            "SELECT rxcui, display_name, cutoff_quarter,"
            " (embedding OPERATOR(public.<=>) CAST(%s AS public.vector))::float8"
            " AS distance FROM drug_profiles"
            " WHERE embedding IS NOT NULL AND profile_text ILIKE %s"
            " ORDER BY distance, rxcui LIMIT %s",
            (_vector_literal(query_vector), f"%{must_contain}%", k),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT rxcui, display_name, cutoff_quarter,"
            " (embedding OPERATOR(public.<=>) CAST(%s AS public.vector))::float8"
            " AS distance FROM drug_profiles"
            " WHERE embedding IS NOT NULL"
            " ORDER BY distance, rxcui LIMIT %s",
            (_vector_literal(query_vector), k),
        ).fetchall()
    return [
        SearchHit(
            rxcui=str(row[0]),
            display_name=str(row[1]),
            distance=float(row[3]),
            cutoff_quarter=str(row[2]),
        )
        for row in rows
    ]
