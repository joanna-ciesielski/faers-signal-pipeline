# Application note: disproportionality signal detection over FDA FAERS

*A methods-style write-up of what this pipeline computes, the policy
choices behind it, and what its outputs do and do not mean. Numbers refer
to the two development quarters (2026Q1 + 2026Q2) and carry their PR
evidence references; they will be refreshed at full-history backfill.*

> **Standing disclaimer.** FAERS contains spontaneous adverse-event
> reports: no denominators, possible duplicates, unverified causality,
> reporting stimulated by publicity and litigation. Everything below is
> **signal detection, not risk quantification**, produced by a research
> and monitoring tool — not clinical decision support, not a system of
> record, not medical advice.

## 1. Data source

FDA publishes FAERS as quarterly ASCII extracts: seven `$`-delimited
tables (DEMO, DRUG, REAC, OUTC, RPSR, THER, INDI) plus a deleted-cases
list. The format drifts across eras (the 2012Q4 ISR→case/version
transition, the 2014Q3 field expansion, the 2015 `gndr_cod`→`sex`
rename); this pipeline models eras explicitly and **verifies the layout
of every downloaded archive against its era spec before loading**
(machine-readable findings; verification failure fails the quarter).
Files carry real-world quirks — no quoting, embedded line breaks,
latin-1 bytes, blank lines, partial dates — each handled as a named,
tested case in the streaming parser. Rows violating the data contracts
are quarantined with all their reason codes, never silently dropped or
repaired; on the dev corpus, 10,488,110 rows staged with **zero
unexplained rejections** (PR #3). The one systematic rejection found —
`role_cod = 'DN'` — was traced to FDA's January-2025 ASC_NTS revision
and admitted as a cited vocabulary change rather than papered over.

## 2. Case deduplication

FAERS reports arrive as versioned cases (`primaryid` = `caseid` +
`caseversion`); quarters re-ship revisions, and quarterly deleted-cases
lists retract cases from the whole history. The resolution policy
(`docs/dedup-policy.md`): the numerically highest version wins; equal
versions resolve to the latest quarter's copy; a case is deleted iff its
latest deletion is at or after its latest sighting (same-quarter tie →
deletion wins); a strictly later sighting resurrects. The merge is
rebuilt from the staged union, so **quarter load order cannot change the
outcome** — gated end-to-end (q1→q2 vs q2→q1 produces byte-identical
tables) and at the pure level by a 200-case permutation property test.
Dev corpus: 819,683 version sightings → 793,001 unique cases → 792,346
current + 655 deleted, with the accounting identities verified on the
real data (PR #4). 9,697 deletions referenced cases outside the staged
window (`never_seen_deletions`) — expected at two-quarter scope, and a
number that should trend to zero as the backfill widens.

## 3. Drug normalization

Verbatim drug strings (DRUGNAME, PROD_AI) map to RxNorm concepts
(RXCUI) exclusively via the open RxNav REST API — the licensed full
RxNorm release is deliberately not assumed. Cleaning is deterministic
rule-based normalization; **no fuzzy matching** (ADR 0006: silent wrong
merges are worse than honest unmapped rows). Lookups are cached in
`drug_map`; a completed run re-executed makes **zero API calls**
(CI-gated). Dev corpus: 95.09% row-weighted mapping coverage across
50,282 distinct cleaned names; the unmapped remainder is published
frequency-ranked, not hidden (PR #5).

## 4. Statistical methods

For each (drug D, reaction R) pair, a case-level 2×2 table over current
(deduplicated) cases:

|            | reaction R | other reactions |
|------------|------------|-----------------|
| drug D     | a          | b               |
| other drugs| c          | d               |

- **PRR** (Evans SJ, Waller PC, Davis S., *Pharmacoepidemiol Drug Saf*
  2001;10(6):483–6): PRR = (a/(a+b)) / (c/(c+d)), with
  SE(ln PRR) = √(1/a − 1/(a+b) + 1/c − 1/(c+d)) and 95% CI
  exp(ln PRR ± 1.96·SE).
- **ROR** (van Puijenbroek EP et al., *Pharmacoepidemiol Drug Saf*
  2002;11(1):3–10): ROR = ad/bc, with SE(ln ROR) = √(1/a + 1/b + 1/c +
  1/d) and 95% CI exp(ln ROR ± 1.96·SE).
- **Pearson χ²**, 1 df, **without** Yates continuity correction (a
  documented choice, pinned by hand-computed goldens).
- Inclusion threshold **a ≥ 3**; zero-margin statistics return null
  rather than fabricated values.

Implementation values were validated three ways before any real-data
run: hand-computed golden values on a synthetic 20-case corpus,
independent recomputation with scipy/statsmodels, and mutation
spot-checks — all three in agreement (PR #6). Recomputation over the
real corpus is **byte-identical** (proven by export diff).

Dev corpus: 615,583 qualifying pairs.

## 5. Ranking: why not chi-square, and why per-drug

Two findings from the first real-data run shape every ranked surface:

1. **Raw χ² is degenerate as a ranking key.** Perfect-overlap cells
   (b = 0 or c = 0 — a drug reported only with one reaction, or a
   reaction only with one drug) reach χ² ≈ N regardless of relevance.
   Ranking therefore uses the **ROR 95% CI lower bound**, the
   conservative standard; all statistics remain queryable.
2. **Global cross-drug top-N lists are structurally dominated by
   rare-reaction concomitant clusters.** A few case-series reports give
   every co-prescribed drug a near-perfect small cell (observed:
   "Amyloid arthropathy" across four RXCUIs with b, c ≈ 1–2). This is
   inherent to spontaneous reporting, not a defect to filter away with
   ad-hoc thresholds. The meaningful product surface is **per-drug**
   ranking, where the artifact evaporates — and that is the only ranked
   surface this project serves.

**Face validity.** On the per-drug surface, medroxyprogesterone acetate
ranks Meningioma first (a = 9,668, ROR CI lower bound ≈ 55,800),
coherently across three related MedDRA PTs (benign and malignant
variants), while background reactions (headache, nausea, fatigue)
correctly show ROR ≪ 1 — independently reproducing the
literature-documented progestogen–meningioma association. Reporting for
this pair is plausibly litigation-stimulated; the magnitude is a signal
property, not a risk estimate.

## 6. Semantic profiles (Phase 6)

Each drug with qualifying pairs gets a deterministic plain-text safety
profile (versioned format; reactions ordered by ROR CI lower bound;
byte-stable across rebuilds), embedded with bge-small-en-v1.5 (384-d,
cosine) into pgvector under an HNSW index. Re-embedding is cache-first:
an unchanged database embeds zero profiles, which is the standing
reproducibility proof (3,586 profiles; second run `embedded=0` — PR #8).
Search is hybrid: nearest-by-meaning with an optional exact-substring
filter on the profile text. Reaction terms appear exactly as published
(MedDRA strings only; no hierarchy — ADR 0004).

## 7. Reproducibility and engineering controls

Determinism, idempotency, and order-independence are CI-gated
invariants, not aspirations: archives are SHA-256-verified; loads are
delete-then-load idempotent per (quarter, table); the merge is
order-independent by construction; signal recomputation is
byte-identical; embeddings are change-driven. Orchestration (Temporal)
adds an idempotency boundary at the workflow ID, non-retryable failure
for poison inputs, degrade-not-fail for RxNav outages, and a
failure-injection suite (worker killed mid-run, poison archive, API
outage, duplicate start) that runs against a real Temporal server in CI.
A two-quarter orchestrated re-run converged to the exact prior state
(PR #7). Storage is governed by checksummed plain-SQL migrations,
least-privilege roles (the web-serving role cannot read raw report
payloads), and a trigger-enforced append-only audit log (PR #8; design
notes in §164.312 vocabulary with explicit scope honesty:
`docs/hipaa-alignment.md`). Quality gate on every commit: `ruff`,
`mypy --strict`, 239 offline deterministic tests, coverage ≥ 90%.

## 8. Limitations

Spontaneous reporting bias, no exposure denominators, duplicate and
unverifiable reports, indication confounding (drugs prescribed for a
condition accumulate that condition's events), concomitant-drug
clustering (§5), two-quarter scope until the full-history backfill, and
mapping coverage below 100% (§3). None of the statistics here estimate
incidence, prevalence, or relative risk.

*Prepared as part of Phase 7. Questions this note cannot answer should
be treated as gaps in the note — file an issue.*
