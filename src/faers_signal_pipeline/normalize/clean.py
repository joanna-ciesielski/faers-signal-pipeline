"""Deterministic pre-clean of reported drug names — pure functions only.

Rules are fixed and inspectable: whitespace, case, trailing punctuation,
and one optional fallback candidate with a trailing salt/hydrate designation
removed. The suffix list covers common pharmaceutical salt and hydrate
designations as used in FDA substance naming (e.g. USP monograph titles);
it is deliberately short and extended only with citation, never guessed.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")

#: Common trailing salt/ester/hydrate designations in reported drug names.
SALT_SUFFIXES: frozenset[str] = frozenset(
    {
        "HYDROCHLORIDE",
        "HCL",
        "SODIUM",
        "POTASSIUM",
        "CALCIUM",
        "MAGNESIUM",
        "SULFATE",
        "ACETATE",
        "TARTRATE",
        "BITARTRATE",
        "MALEATE",
        "MESYLATE",
        "BESYLATE",
        "TOSYLATE",
        "CITRATE",
        "FUMARATE",
        "SUCCINATE",
        "PHOSPHATE",
        "NITRATE",
        "BROMIDE",
        "CHLORIDE",
        "IODIDE",
        "DIHYDRATE",
        "MONOHYDRATE",
        "HEMIHYDRATE",
        "ANHYDROUS",
    }
)


def clean_name(raw: str) -> str:
    """Canonical form of a reported name: trimmed, collapsed, uppercased,
    trailing periods removed. Idempotent (property-tested)."""
    collapsed = _WHITESPACE.sub(" ", raw).strip()
    return collapsed.rstrip(".").strip().upper()


def candidate_names(raw: str) -> tuple[str, ...]:
    """Lookup candidates in priority order: the cleaned name, then (when it
    ends in a documented salt/hydrate token and more than one token remains)
    the salt-stripped fallback. Empty input yields no candidates."""
    cleaned = clean_name(raw)
    if not cleaned:
        return ()
    tokens = cleaned.split(" ")
    if len(tokens) > 1 and tokens[-1] in SALT_SUFFIXES:
        stripped = " ".join(tokens[:-1])
        if stripped != cleaned:
            return (cleaned, stripped)
    return (cleaned,)
