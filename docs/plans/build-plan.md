# Build Plan — FAERS Signal Pipeline & Live Explorer (v3.0)

> This is the in-repo working copy of the build plan. Boundary rules are
> stated generically here; the maintainer's private planning documents are
> the authoritative source for engagement-specific constraints.

**What this project is:** a public pharmacovigilance data platform — Python
3.12 ETL over FDA FAERS quarterly extracts, orchestrated with Temporal
(quarterly Schedule + backfill), landing in PostgreSQL 16 + pgvector,
computing PRR/ROR disproportionality statistics behind a CI quality gate,
published as a free read-only web explorer on AWS, with watchlist email
alerts as the single monetization experiment.

## Monetization strategy — decided

1. **Free public tier, NO advertising. Decided — do not re-open.** Full
   rationale recorded in `docs/adr/0005-no-ads-free-tier.md`. If
   consumer-side goodwill revenue is ever wanted: a donation link or a
   vetted non-programmatic sponsor line — nothing else.
2. **Revenue experiment = B2B watchlist alerts (Phase 9).** Target buyers in
   priority order: mass-tort/product-liability law firms, biotech
   competitive/investor intelligence, small pharma/CRO exploratory triage
   (capped pricing until a validated offering exists).
3. **The clean-data API is a funnel, not the product.** Free with rate
   limits; it markets pipeline quality to technical evaluators.
4. **The floor is the credential.** Direct revenue is upside; the certain
   return is an operated production service as a professional flagship. The
   Phase 9 decision gate keeps product investment honest.
5. **Positioning, always:** research and monitoring tool. Never clinical
   decision support, never a PV system of record, no medical advice.

**Boundary rules (non-negotiable):**

1. No material, schema, naming, or concept from any client engagement enters
   this repository. This platform covers drugs (FAERS), deliberately **not**
   medical devices (MAUDE), and carries no investment/diligence framing in
   the product; all alert subscribers receive the same generic alerts.
2. Licensing discipline as a feature: FAERS files are US-government public
   domain (CI samples committable). RxNorm only via the open RxNav REST API
   (full RxNorm release requires a free UMLS license — documented, not
   assumed). REAC/INDI terms are MedDRA Preferred Term strings: **use
   strings as published; never reconstruct or embed the MedDRA hierarchy**
   (subscription-licensed). ADR each.

**Effort budget: 60–90 hours across 10 phases** (Phases 0–7 ≈ 40–60h;
Phase 8 ≈ 12–20h; Phase 9 ≈ 8–12h plus outreach). Each phase is a PR with
green CI. **Phase 8 does not start until the Phase 5 quality gate is green
and a full-history backfill has run** — a live service on an ungated
pipeline is the anti-pattern this project exists to argue against.

**Operating cost ceiling: $30/month.** Exceeding it requires a written
decision.

## Fixed decisions — do not re-open without new evidence

1. **Temporal over Airflow**, with **Temporal Schedules** for quarterly
   ingestion (ADR 0001).
2. **One storage engine: PostgreSQL 16 + pgvector**, signal statistics
   precomputed at ingest into indexed serving tables (ADR 0002).
3. **Python 3.12, uv, ruff, mypy --strict, pytest, pydantic v2 + pandera;
   Polars** for large delimited files (ADR 0003).
4. **FAERS ASCII quarterly extracts** (DEMO, DRUG, REAC, OUTC, THER, INDI,
   RPSR; $-delimited). XML noted as swap.
5. **Scope: 2 recent quarters + 1 backfill quarter** for dev; CI uses small
   committed public-domain samples + synthetic edge-case files.
   Full-history backfill is a config change, executed once before Phase 8.
6. **Case deduplication policy is the centerpiece** (FDA guidance basis):
   latest PRIMARYID version per CASEID wins across quarters; quarterly
   deleted-case lists honored; late-arriving older versions ignored
   idempotently; full history retained in case_versions. Pure module,
   exhaustive tests, order-independence gate.
7. **Signal statistics: PRR and ROR with 95% CIs + chi-square**, 2×2
   contingency from current_cases, a≥3 threshold, formulas cited to
   standard pharmacovigilance literature; hand-computed golden values on
   synthetic data. BCPNN/EBGM noted as swaps.
8. **Analytical honesty is a product feature:** FAERS output is signal
   detection, not risk quantification; plain-language disclaimer block on
   every results page. Differentiation is engineering transparency, not
   consumer health claims.
9. **Determinism and idempotency are CI gates.** Byte-identical signal
   tables across runs; zero duplicate loads on re-run; run manifests (file
   SHA-256, code version, config hash) in runs.
10. **Treat public data as if it were PHI** in architecture: least-privilege
    roles, append-only audit log, no raw records in logs (Phase 6).
11. **Live tier: read-only, no accounts, no ads.** FastAPI +
    server-rendered pages (Jinja; htmx at most, no SPA); Cloudflare free
    tier; rate-limited API; single small AWS instance. ECS/RDS documented
    as the scale-up swap, not built.
12. **Alerts before dashboards.** The only interactive investment beyond
    search-and-view is the Phase 9 watchlist alerting. No user dashboards,
    no saved views, no auth beyond the alert email list in v1.

## Phases

### Phase 0 — Scaffold & data acquisition (3–5h)

- Repo scaffold: uv, strict mypy/ruff/pytest, GitHub Actions CI,
  docker-compose.yml (Postgres+pgvector, Temporal dev server),
  .env.example, MIT license, README skeleton with boundary + licensing +
  positioning statements.
- scripts/fetch_quarter.py: download + checksum a named FAERS quarter;
  cached; verify layout against the quarter's README (layouts drift across
  eras — parse defensively).
- ADRs 0001–0005.
- **DoD:** fresh clone → docker compose up + uv run pytest green <10 min;
  one real quarter fetched and checksummed.

### Phase 1 — ETL core: parse → validate → stage (6–9h)

- ingest/: $-delimited parsers per table → typed records; tolerant of known
  FAERS quirks, each quirk a named test case.
- contracts/: pydantic row models + pandera frame checks. **Quarantine
  path:** violations → quarantine with machine-readable reasons; never
  dropped, never partially loaded.
- Per-quarter data-quality report as artifact + runs row.
- Property-based tests (hypothesis).
- **DoD:** dev quarters load or quarantine cleanly; zero violations pass;
  coverage ≥90% on ingest/ + contracts/.

### Phase 2 — Case versioning & deduplication (5–8h)

- dedup/: pure functions; scenario tests (new case, same-quarter revision,
  cross-quarter revision, deletion, revision-after-deletion, out-of-order
  loads); docs/dedup-policy.md.
- **DoD:** all scenarios green; **order-independence test** — any quarter
  load order converges to the identical current_cases set.

### Phase 3 — Drug normalization (4–6h)

- normalize/: DRUGNAME/PROD_AI → RXCUI via RxNav REST; aggressive local
  cache; unmatched → unmapped tier with frequency-ranked report.
  Deterministic pre-clean as pure functions; no fuzzy matching v1.
- **DoD:** ≥80% of drug-report rows mapped on dev quarters; second run
  zero-API-call (asserted).

### Phase 4 — Signal statistics (5–8h)

- signals/: 2×2 tables from current_cases; PRR + ROR with 95% CIs,
  chi-square, a≥3; ranked signal table per quarter-cutoff written to
  indexed serving tables.
- Golden tests: synthetic mini-corpus, hand-computed statistics (worked
  arithmetic in comments); mutation spot-check. docs/validation.md
  reproduces 2–3 well-known historical signals; limitations first.
- **DoD:** goldens green; ranked signals byte-identical across runs.

### Phase 5 — Temporal orchestration & schedules (7–10h)

- IngestQuarter workflow; Backfill parent (bounded concurrency); quarterly
  Schedule with overlap policy + catch-up window; activities with
  heartbeats, transient-vs-non-retryable retry split, idempotency keys.
- **Failure-injection suite** (time-skipping): worker kill → durable
  resume; poison file → quarantine, batch completes; RxNav outage →
  degrade to unmapped; duplicate schedule fire → idempotent no-op.
- docs/runbook.md.
- **DoD:** full dev backfill via Temporal locally; failure-injection suite
  green in CI.

### Phase 6 — Storage, pgvector & HIPAA-alignment doc (6–9h)

- Plain-SQL migrations: cases, case_versions, drugs, reactions, outcomes,
  drug_map, signal_stats, runs, quarantine, audit_log (append-only);
  roles etl_writer / readonly_web / readonly_analyst; isolation tests.
- pgvector: deterministic per-drug safety-profile summaries embedded with
  local bge-small-en-v1.5; HNSW index; hybrid query CLI demo.
- docs/hipaa-alignment.md: scope honesty (public data, HIPAA does not
  apply, none claimed); §164.312 mapping; identified-reports discussion;
  advisory checklist.
- **DoD:** ERD in README; role isolation tests pass; audit rows on every
  load; semantic demo reproducible; zero compliance claims.

### Phase 7 — Docs & portfolio assets (3–5h)

- Full README (architecture diagram, quickstart, results, analytical
  honesty, boundary/licensing/positioning, out-of-scope list);
  docs/application-note.md; diagram assets.
- **DoD:** stranger-clone <10 min to green.

### Phase 8 — Live explorer service on AWS (12–20h) — GATE: Phase 5 quality gate green + full-history backfill run

- web/: FastAPI + Jinja (htmx at most). Pages: home/search; drug page
  (ranked signals with PRR/ROR + CIs, trend chart, top outcomes,
  **disclaimer block on every results page**); methodology page; status
  page; rate-limited JSON API.
- Deploy: single small AWS instance running the compose stack; TLS via
  Caddy/nginx; Cloudflare free in front; nightly pg_dump to S3 + restore
  drill performed once; uptime monitor; deploy runbook; log hygiene.
- **DoD:** live URL serving full-history signals; production schedule run;
  uptime ≥14 consecutive days; restore drill documented; under $30/mo.

### Phase 9 — Watchlist alerts & validation gate (8–12h + outreach)

- Email watchlists on the quarterly Schedule; double-opt-in; plain-text
  template; free during beta; Stripe-ready seam designed, not built.
- Validation-by-conversation with 3–5 prospects; notes kept privately.
- **90-day decision gate** from Phase 8 launch with a pre-committed rule:
  ≥2 prospects at a named price → invest further; otherwise freeze feature
  work, keep the service as the flagship. Memo template with date set.
- **DoD:** alert fires on synthetic threshold crossing in test and once in
  production; beta signup live; decision-gate memo dated.

## Risk register

- FAERS layout drift across eras → defensive parsing + per-era fixtures.
- RxNav availability → cache-first; CI fully offline.
- MedDRA licensing missteps → strings-as-published only; reviewed at
  Phases 1, 6, 8; ADR 0004 is the guardrail.
- Statistical credibility → cited formulas, CIs always shown, no
  risk-quantification claims; methodology page leads with limitations.
- Live-service reputational risk → uptime monitor, status page; if retired,
  take it down cleanly and let the repo stand.
- Consumer misreading → every-page disclaimer; no severity color-coding;
  no ads ever (decided).
- Scope creep toward dashboards/auth/SPA → fixed decisions 11–12.
- Cost creep → $30/mo ceiling with written-decision override.

## Definition of done (project)

Phases 0–7: dedup order-independence + determinism + idempotency CI-gated;
failure-injection suite green; schedule + backfill demonstrated; HIPAA doc
complete; README stranger-reproducible; portfolio assets shipped.
Phase 8: live URL, production schedule run, 14-day uptime, restore drill,
under cost ceiling. Phase 9: alert proven in production, beta signup live,
decision-gate memo dated. Monetization decisions recorded in ADRs and README.
