"""Deterministic per-drug safety-profile texts.

Each mapped drug that has qualifying signal rows gets one plain-text
profile summarizing its top disproportionality signals. The text is the
EMBEDDING INPUT for semantic search (vectors/embed.py), so it must be
byte-stable across rebuilds from the same database state:

- versioned format (``profile-version: 1`` header);
- reactions ordered by (ror_ci_low DESC NULLS LAST, pt ASC) — the same
  ranking the report uses, with an explicit lexicographic tiebreak;
- display name = the lexicographically smallest matched ``name_key`` for
  the rxcui. A deliberate, drift-free choice: frequency-weighted naming
  would need the clean-name logic re-run over staging (a second
  implementation of cleaning — the exact drift risk this repo bans).
- numbers rendered with ``str()`` from the stored (already-rounded)
  values — no re-computation at profile time.

MedDRA boundary (ADR 0004): reaction terms appear exactly as published
strings; no hierarchy is used or reconstructed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import groupby

import psycopg

PROFILE_FORMAT_VERSION = 1
DEFAULT_TOP_N = 20


@dataclass(frozen=True, slots=True)
class ProfileBuildOutcome:
    cutoff_quarter: str | None
    profiles_built: int
    profiles_removed: int


def _render_profile(
    rxcui: str,
    display_name: str,
    cutoff_quarter: str,
    reactions: list[tuple[str, int, float | None]],
) -> str:
    lines = [
        f"profile-version: {PROFILE_FORMAT_VERSION}",
        f"rxcui: {rxcui}",
        f"drug: {display_name}",
        f"cutoff: {cutoff_quarter}",
        f"signals: {len(reactions)}",
        "top reactions by ror_ci_low:",
    ]
    for pt, a, ror_ci_low in reactions:
        shown = "n/a" if ror_ci_low is None else str(ror_ci_low)
        lines.append(f"- {pt} (a={a}, ror_ci_low={shown})")
    return "\n".join(lines) + "\n"


def build_profiles(conn: psycopg.Connection, top_n: int = DEFAULT_TOP_N) -> ProfileBuildOutcome:
    """(Re)build profile texts for the latest cutoff; deterministic.

    Rebuilds are full upserts keyed on (cutoff_quarter, rxcui); drugs that
    no longer have qualifying rows at this cutoff are removed. Embeddings
    are NOT touched here — vectors/embed.py compares ``profile_sha256``
    against ``embedded_sha`` and re-embeds only what changed.
    """
    row = conn.execute("SELECT max(cutoff_quarter) FROM signal_stats").fetchone()
    cutoff = row[0] if row is not None else None
    if cutoff is None:
        return ProfileBuildOutcome(cutoff_quarter=None, profiles_built=0, profiles_removed=0)

    names = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT rxcui, min(name_key) FROM drug_map"
            " WHERE status = 'matched' AND rxcui IS NOT NULL GROUP BY rxcui"
        ).fetchall()
    }
    signal_rows = conn.execute(
        "SELECT rxcui, pt, a, ror_ci_low FROM signal_stats"
        " WHERE cutoff_quarter = %s"
        " ORDER BY rxcui, ror_ci_low DESC NULLS LAST, pt",
        (cutoff,),
    ).fetchall()

    built = 0
    seen: list[str] = []
    with conn.cursor() as cur, conn.transaction():
        for rxcui, group in groupby(signal_rows, key=lambda r: str(r[0])):
            reactions = [(str(pt), int(a), low) for _, pt, a, low in group][:top_n]
            display_name = names.get(rxcui, rxcui)
            text = _render_profile(rxcui, display_name, str(cutoff), reactions)
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            cur.execute(
                "INSERT INTO drug_profiles"
                " (cutoff_quarter, rxcui, display_name, profile_text, profile_sha256)"
                " VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (cutoff_quarter, rxcui) DO UPDATE SET"
                " display_name = EXCLUDED.display_name,"
                " profile_text = EXCLUDED.profile_text,"
                " profile_sha256 = EXCLUDED.profile_sha256,"
                " built_at = now()",
                (cutoff, rxcui, display_name, text, sha),
            )
            built += 1
            seen.append(rxcui)
        cur.execute(
            "DELETE FROM drug_profiles WHERE cutoff_quarter = %s AND NOT (rxcui = ANY(%s))",
            (cutoff, seen),
        )
        removed = cur.rowcount
    return ProfileBuildOutcome(
        cutoff_quarter=str(cutoff), profiles_built=built, profiles_removed=int(removed)
    )
