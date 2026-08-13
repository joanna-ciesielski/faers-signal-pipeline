# ADR 0006 — Drug normalization: deterministic rules only, no fuzzy matching (v1)

- Status: accepted
- Date: 2026-08-13

## Context

Reported drug names in FAERS are messy: verbatim consumer text, salt and
hydrate suffixes, trade/generic mixtures, typos. Normalization maps them to
RxNorm RXCUIs via the open RxNav REST API (ADR 0004: never the
UMLS-licensed full release; only the RXCUI and our own match metadata are
persisted).

## Decision

v1 uses only deterministic, inspectable transformations: whitespace/case
canonicalization, trailing-punctuation removal, and a single cited list of
trailing salt/hydrate designations tried as a *fallback* candidate — plus
RxNav's own normalized search (`search=2`). No edit-distance matching, no
embedding similarity, no LLM guessing.

Rationale: every mapping this pipeline makes must be explainable to a
skeptical reviewer in one sentence ("the name, cleaned by these fixed
rules, resolved in RxNorm"). A fuzzy match trades that auditability for
coverage — the wrong trade for a signal-detection platform, where a wrong
drug mapping silently corrupts statistics. Unmapped names are a *reported
deliverable* (frequency-ranked), not a failure to hide.

## When fuzzy/embedding matching would win

A curated-review workflow where a human approves each proposed match, or a
use case where recall matters more than per-mapping auditability (e.g.
exploratory search). If added later, it would be a separate, clearly
labeled tier — never silently merged into the deterministic mappings.
