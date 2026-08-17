# faers-signal-pipeline

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21982755.svg)](https://doi.org/10.5281/zenodo.21982755)

A public pharmacovigilance data platform: Python 3.12 ETL over FDA FAERS
quarterly extracts, orchestrated with Temporal (quarterly Schedule +
backfill), landing in PostgreSQL 16 + pgvector, computing PRR/ROR
disproportionality statistics behind a CI quality gate — later published as a
free, read-only web explorer.

> **Status: core platform complete (phases 0–6 merged; PRs #2–#8).**
> Fetch → verify → stage → deduplicate → normalize → signal statistics →
> Temporal orchestration → migrations/roles/audit → semantic search, each
> phase merged through PR review with green CI and evidence posted on the
> PR. Next: the full-history backfill and the public web explorer
> (`docs/plans/build-plan.md`). Nothing here is a finished analysis.

## What this is — and is not

This is a **research and monitoring tool** built on public FDA data. It is
**not** clinical decision support, **not** a pharmacovigilance system of
record, and provides **no medical advice**.

**Read this before interpreting any output of this project:**

> FAERS contains spontaneous adverse-event reports. There are **no
> denominators** (no exposure counts), reports may be duplicated or
> unverified, and reporting is stimulated by publicity and litigation.
> Disproportionality statistics (PRR/ROR) computed here are **signal
> detection, not risk quantification**. A signal is a reason to look closer,
> never evidence that a drug causes an effect. Nothing in this repository or
> any service built from it is medical advice; do not make treatment
> decisions from it — talk to a qualified clinician.

This disclaimer accompanies every results surface this project produces.

## Results (dev corpus: 2026Q1 + 2026Q2, as of 2026-08)

Every number below is reproducible from this repository against the two
development quarters, and each was posted as evidence on the PR that
introduced it (PRs #3–#8). They will be refreshed at the full-history
backfill.

| What | Number | Where it comes from |
|---|---|---|
| Rows staged (7 tables × 2 quarters) | 10,488,110 | per-quarter DQ reports (PR #3) |
| Rows quarantined, unexplained | **0** | every rejection carries machine-readable reason codes; the one systematic rejection found (role_cod `DN`) was traced to the Jan-2025 ASC_NTS revision and admitted with a cited vocabulary change |
| Case version sightings → current cases | 819,683 → **792,346** | merge report; accounting identities verified on real data (PR #4) |
| Drug-name mapping coverage (row-weighted) | **95.09%** | RxNav mapping report; re-runs make zero API calls (PR #5) |
| Qualifying (drug, reaction) pairs, a ≥ 3 | **615,583** | `signal_stats` (PR #6) |
| Known signal reproduced | medroxyprogesterone acetate × Meningioma, a = 9,668 | per-drug ranking by ROR CI lower bound (PR #6) — the literature-documented progestogen–meningioma association surfaced independently |
| Orchestrated re-run convergence | byte-identical state | two-quarter Temporal backfill reproduced the exact same `current_cases` and `signal_stats` counts (PR #7) |
| Drug safety profiles embedded | 3,586 | bge-small-en-v1.5; re-run embeds **0** (unchanged database does zero work — PR #8) |
| Tests / coverage | 239 passed / 91.75% | CI, every commit |

## Semantic search (Phase 6)

Deterministic per-drug safety-profile texts, embedded and HNSW-indexed in
pgvector, searchable by meaning with an optional exact-term filter:

```bash
uv sync --extra vectors                          # real model (one-time download)
uv run python scripts/build_embeddings.py
uv run python scripts/semantic_search.py "progestogen meningioma risk" --k 5
#  1. MEDROXYPROGESTERONE  2. PROMEGESTONE  3. MIFEPRISTONE  4. DROSPIRENONE ...
uv run python scripts/semantic_search.py "hair loss" --must-contain Alopecia
#  1. RITLECITINIB (a JAK inhibitor approved for alopecia areata) ...
```

The disclaimer above applies to these outputs too: retrieval quality is
not evidence of causation.

## Quickstart

**Fast path — clone to green in under 10 minutes** (no FAERS download;
tests run on committed synthetic fixtures and a real-format CI sample):

```bash
git clone https://github.com/joanna-ciesielski/faers-signal-pipeline.git
cd faers-signal-pipeline
cp .env.example .env        # set a local Postgres password
docker compose up -d        # PostgreSQL 16 + pgvector, Temporal dev server
uv sync                     # installs pinned CPython 3.12 + locked deps
uv run pytest               # 239 tests, offline, deterministic, coverage-gated
```

**Full path — real data** (each quarter's archive is a ~60–90 MB
download expanding to ~5M rows; a full load takes a few minutes per
quarter):

```bash
export DATABASE_URL="postgresql://faers:YOUR_PASSWORD@127.0.0.1:5432/faers"
uv run python scripts/fetch_quarter.py 2026q2   # fetch + checksum + layout-verify
uv run python scripts/load_quarter.py 2026q2    # parse -> validate -> stage + DQ report
uv run python scripts/merge_cases.py            # case-version dedup -> current_cases
uv run python scripts/map_drugs.py              # RxNav mapping (throttled, resumable)
uv run python scripts/compute_signals.py        # PRR/ROR/chi-square -> signal_stats
```

Or let Temporal run the whole chain (`docs/runbook.md`):

```bash
uv run python scripts/run_worker.py                              # terminal 1
uv run python scripts/pipeline_workflow.py backfill 2026q1 2026q2  # terminal 2
```

Every line of a quarter either stages cleanly or lands in the `quarantine`
table with machine-readable reason codes — nothing is silently dropped or
repaired. The per-quarter data-quality report (`data/reports/dq-*.json`)
summarizes rows loaded, quarantine reasons, join orphans, and the
deleted-cases list.

## Boundary & licensing statements

- **Independence:** this repository contains no material, schema, naming, or
  concept from any client engagement. It is built exclusively from public
  FDA documentation and data.
- **Scope:** drugs and biologics (FAERS), deliberately **not** medical
  devices (MAUDE).
- **FAERS data** is published by the US FDA and is US-government work
  (public domain); small CI samples are committable.
- **RxNorm** is used only via the open [RxNav REST API](https://lhncbc.nlm.nih.gov/RxNav/).
  The full RxNorm release requires a (free) UMLS license and is therefore
  documented as an alternative, not assumed.
- **MedDRA:** reaction and indication fields in FAERS are MedDRA Preferred
  Term **strings**. This project uses those strings exactly as published and
  **never reconstructs, embeds, or displays the MedDRA hierarchy**, which is
  subscription-licensed. See `docs/adr/0004-terminology-licensing.md`.
- The public tier of any service built from this pipeline is read-only, has
  no accounts, and carries **no advertising**
  (`docs/adr/0005-no-ads-free-tier.md`).

## Architecture

```mermaid
flowchart LR
    FDA["FDA FAERS<br/>quarterly zips"] -->|"fetch + sha256 + layout verify"| STG[("stg_* staging<br/>+ quarantine")]
    STG -->|"case-version dedup<br/>order-independent"| CC[("current_cases")]
    STG -->|"clean names"| RXN["RxNav API<br/>cache-first"] --> DM[("drug_map")]
    CC --> SIG["2x2 case-level tables<br/>PRR / ROR / chi-square"]
    DM --> SIG
    SIG --> SS[("signal_stats")]
    SS -->|"deterministic profile texts"| EMB["bge-small-en-v1.5"] --> DP[("drug_profiles<br/>pgvector HNSW")]
    TEMP["Temporal<br/>schedule + backfill"] -. orchestrates .-> STG
    TEMP -. orchestrates .-> SS
    MIG["plain-SQL migrations<br/>roles + audit_log"] -. governs .-> STG
    MIG -. governs .-> DP
```

- `quarter.py`, `layout.py` — quarter/era model and era-keyed layout specs;
  layouts are **verified against every downloaded quarter** (FAERS layouts
  drift across eras, so the expected schema is data, not assumption).
- `fetch.py` + `scripts/fetch_quarter.py` — download, SHA-256, cache with
  zero-network-on-hit, layout verification with machine-readable findings.
- `ingest/` — streaming $-delimited parser built around documented FAERS
  quirks (no quoting, embedded line breaks, latin-1 bytes, blank lines,
  partial dates), each quirk a named test case; deleted-cases list parser
  (format verified on real data).
- `contracts/` — pydantic row models; Polars frame checks that route
  violations to quarantine with *all* their reason codes; pandera schemas
  certify what passes (pipeline invariants, not input filtering).
- `db/` + `pipeline.py` + `scripts/load_quarter.py` — transactional staging
  into Postgres (one transaction per quarter+table; idempotent re-runs load
  zero duplicates — CI-gated), quarantine and runs lineage tables,
  per-quarter DQ report artifact.
- `dedup/` + `db/cases.py` + `scripts/merge_cases.py` — the case
  deduplication centerpiece: a pure resolution module (latest version per
  case wins; quarterly deleted-cases lists honored; late-arriving older
  versions ignored; full history in `case_versions`), rebuilt from the
  staged union so **quarter load order cannot change the outcome** —
  CI-gated end-to-end and by a 200-case permutation property test. Policy,
  FDA basis, and residual duplicate risk: `docs/dedup-policy.md`.
- `normalize/` + `scripts/map_drugs.py` — DRUGNAME/PROD_AI → RxNorm RXCUI
  via the open RxNav REST API only (no licensed release): deterministic
  pre-clean rules (no fuzzy matching — ADR 0006), polite throttled client,
  and an aggressive `drug_map` cache making re-runs zero-API-call
  (CI-gated). Unmapped names are a reported deliverable, frequency-ranked,
  never hidden.
- `signals/` + `scripts/compute_signals.py` — case-level 2x2 contingency
  tables from deduplicated cases, PRR/ROR with 95% CIs and chi-square
  (cited formulas), a>=3 threshold, written to the indexed `signal_stats`
  serving table; golden values hand-computed by the maintainer on a
  synthetic corpus (never invented by the implementation). Every results
  artifact carries the signal-detection-not-risk disclaimer.
- `orchestration/` + worker/schedule CLIs — Temporal workflows chaining
  the five stages (fetch → load → merge → map → signals): quarterly
  Schedule (overlap SKIP, 30-day catch-up), bounded-concurrency backfill,
  and a CI failure-injection suite proving durable resume without
  reprocessing, clean poison-file failure, RxNav degrade-not-fail, and
  duplicate-fire idempotency. Operations: `docs/runbook.md`.
- `db/migrations/` + `scripts/migrate.py` — plain-SQL migrations
  (checksummed, immutable once applied) owning every fixed table, the
  role model (`etl_writer` / `readonly_analyst` / `readonly_web`), the
  append-only `audit_log`, and the pgvector objects. Staging tables stay
  generated from the era layout spec — the deliberate exception,
  documented in `db/migrations/README.md`.
- `signals/profiles.py` + `vectors/` — deterministic per-drug safety
  profile texts embedded with bge-small-en-v1.5 (optional extra; a
  deterministic stub keeps CI offline), HNSW-indexed, with a hybrid
  semantic-search CLI. HIPAA-vocabulary design notes (with explicit
  scope honesty: no compliance is claimed): `docs/hipaa-alignment.md`.
- `docs/adr/` — architecture decision records, including the licensing and
  no-ads decisions.

Quality bar (CI-enforced from day one): `ruff` (lint + format),
`mypy --strict`, `pytest` with coverage ≥ 90%, all tests offline and
deterministic.

## Data model (ERD)

Staging tables (`stg_demo`, `stg_drug`, `stg_reac`, `stg_outc`,
`stg_rpsr`, `stg_ther`, `stg_indi`) carry the raw columns of their era
spec plus `quarter`; payload access always joins through the
`current_cases` pointer.

```mermaid
erDiagram
    stg_demo {
        text quarter
        text primaryid
        text caseid
        text caseversion
    }
    stg_drug {
        text quarter
        text primaryid
        text drugname
        text prod_ai
    }
    stg_reac {
        text quarter
        text primaryid
        text pt
    }
    case_versions {
        text caseid PK
        bigint version_int PK
        text quarter PK
        text primaryid
    }
    current_cases {
        text caseid PK
        text caseversion
        text quarter
        text primaryid
    }
    drug_map {
        text name_key PK
        text rxcui
        text status
    }
    signal_stats {
        text cutoff_quarter PK
        text rxcui PK
        text pt PK
        bigint a
        double_precision ror_ci_low
    }
    drug_profiles {
        text cutoff_quarter PK
        text rxcui PK
        text profile_text
        vector384 embedding
    }
    runs {
        bigint id PK
        text kind
        text quarter
        jsonb stats
    }
    audit_log {
        bigint id PK
        text actor
        text action
        jsonb details
    }
    quarantine {
        bigint id PK
        text quarter
        text reason_codes
        text raw_payload
    }
    stg_demo ||--o{ case_versions : "versions from DEMO"
    case_versions ||--|| current_cases : "latest wins"
    current_cases ||--o{ stg_drug : "join (quarter, primaryid)"
    current_cases ||--o{ stg_reac : "join (quarter, primaryid)"
    stg_drug }o--|| drug_map : "cleaned name -> rxcui"
    drug_map ||--o{ signal_stats : "per (rxcui, pt)"
    signal_stats ||--o{ drug_profiles : "top signals -> profile"
    runs ||--|| audit_log : "audited per run"
```

## Analytical honesty

Findings from building this that a results page must say out loud
(details and worked examples: `docs/application-note.md`):

- **Global top-N lists are structurally misleading.** Ranked across all
  drugs, any disproportionality measure is dominated by rare-reaction
  concomitant clusters: a handful of case-series reports gives every
  co-prescribed drug a near-perfect small 2×2 cell. This is inherent to
  spontaneous data, not a bug to filter away. The meaningful surface is
  **per-drug** ranking, where the artifact evaporates — and that is the
  only ranked surface this project serves.
- **Raw chi-square is degenerate as a ranking key.** Perfect-overlap
  cells (b = 0 or c = 0) reach χ² ≈ N regardless of clinical relevance.
  Ranking therefore uses the **ROR 95% CI lower bound** (conservative
  standard); all statistics remain queryable in `signal_stats`.
- **Deletion lists reference all of FAERS history.** At two-quarter
  scope, 9,697 deletions reference cases we have not staged
  (`never_seen_deletions`) — expected, and a health indicator that
  should trend toward zero at full-history backfill.
- **Litigation- and publicity-stimulated reporting inflates counts.**
  The medroxyprogesterone–meningioma cell (a = 9,668) is coherent across
  three related MedDRA PTs and matches the literature — and its
  magnitude still cannot be read as risk, only as a signal.

## Out of scope

Deliberately not in this project: medical devices (MAUDE), the licensed
RxNorm full release, the MedDRA hierarchy, fuzzy drug-name matching
(ADR 0006), causal inference or risk quantification of any kind, patient-
level narratives, clinical decision support, accounts or advertising on
the public tier (ADR 0005).

## Documentation map

- `docs/application-note.md` — methods write-up: data, dedup policy,
  statistics with citations, ranking rationale, limitations.
- `docs/runbook.md` — operations: migrations, worker, schedule, backfill,
  failure semantics, semantic search.
- `docs/dedup-policy.md` — case deduplication rules and FDA basis.
- `docs/hipaa-alignment.md` — storage/access design in §164.312
  vocabulary, with explicit scope honesty (no compliance claimed).
- `docs/adr/` — architecture decision records.
- `docs/plans/build-plan.md` — the phased plan this repo follows.

## License

MIT — see `LICENSE`. (The license covers this code; FAERS data is public
domain; terminology licensing is documented above.)
