# ADR 0004 — Terminology licensing: RxNorm via RxNav API only; MedDRA strings as published, never the hierarchy

- Status: accepted
- Date: 2026-08-12

## Context

Correct handling of third-party clinical terminology licensing is a feature
of this project, not an afterthought.

- FAERS quarterly files are US-government work: public domain, small CI
  samples committable.
- RxNorm's full release is distributed under a (free) UMLS license with
  terms that must be accepted; the open **RxNav REST API** requires none.
- FAERS `reac.pt` / `indi.indi_pt` values are MedDRA Preferred Term
  **strings**. MedDRA itself (the hierarchy: SOC/HLGT/HLT/PT/LLT structure,
  codes, groupings) is subscription-licensed by MSSO.

## Decision

1. Drug normalization uses the RxNav REST API exclusively, with an
   aggressive local cache; the full RxNorm release is documented as the
   licensed alternative, not assumed.
2. MedDRA terms are used **only as the strings FDA publishes in FAERS**.
   This project never reconstructs, re-derives, embeds, or displays the
   MedDRA hierarchy or its codes — including on any future public surface
   (no SOC groupings, no PT→HLT rollups). Reviewed at Phases 1, 6, and 8.

## Consequences

- Reaction-level analysis is PT-string-level only; hierarchy-aware analyses
  (e.g. SOC aggregation) are explicitly out of scope and documented as such.
- If a future user holds a MedDRA license, hierarchy support would be an
  optional, user-supplied input — never shipped data.
