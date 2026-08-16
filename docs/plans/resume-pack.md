# Resume pack

> Assume zero context. Read `docs/plans/build-plan.md` first; its Fixed
> Decisions, Monetization decisions, and Boundary Rules are binding. The
> authoritative (unsanitized) plan is the maintainer's private Drive doc
> "Build Plan B v3 — FAERS Signal Pipeline + Live Explorer Service (FINAL)".

- Updated: 2026-08-16
- Current phase: **6 — Storage, pgvector & HIPAA-alignment doc
  (implemented + verified in sandbox against real Postgres 16 +
  pgvector 0.6; delivered for maintainer review)**. Merged and
  DoD-confirmed: Phase 0 bc8e449 (PR #2), Phase 1 e6bfe07 (PR #3),
  Phase 2 99bbab9 (PR #4), Phase 3 6e6f2b0 (PR #5), Phase 4 2784bc8
  (PR #6), Phase 5 a2921ee (PR #7). Dev quarters 2026q1+2026q2 fully
  processed end-to-end, incl. via Temporal.

## Phase 2 state (2026-08-13)

- Gate green in sandbox: **138 passed, 2 skipped, coverage 96.6%**, mypy
  --strict + ruff clean. Tests were written before the resolve code.
- Implemented: `dedup/resolve.py` (pure; rules: highest caseversion wins
  numerically; equal versions -> latest quarter's copy; deleted iff latest
  deletion quarter >= latest sighting quarter, same-quarter tie -> deletion
  wins; strictly-later sighting resurrects with highest version overall;
  deterministic duplicate collapse, all counted); `db/cases.py`
  (case_versions full history + current_cases pointer table,
  truncate-and-rebuild from staged union in one tx — order-independent by
  construction); `scripts/merge_cases.py`; `docs/dedup-policy.md` (FDA
  basis vs our explicit policy choices vs residual cross-CASEID duplicate
  risk).
- Gates: order-independence proven end-to-end through Postgres (q1->q2 vs
  q2->q1, identical tables, byte-identical merge report) and at pure level
  (200-example hypothesis permutation property). Re-merge idempotent;
  reload+remerge convergent. Adversarial review added named tests:
  v10-beats-v9 numeric ordering, delete/resurrect/delete-again, stats
  accounting identity (dupes+superseded+unique == total;
  current+deleted == unique).
- Note: current_cases is a POINTER table (caseid, caseversion, quarter,
  primaryid); payload joins to staging on (quarter, primaryid). Phase 4
  builds 2x2 tables from current_cases joined to stg_drug/stg_reac via
  primaryid+quarter.

## Phase 2 real-merge results (2026-08-13, maintainer machine, PR #4)

- First real merge over 2026q1+2026q2: version_sightings 819,683 (exactly
  the two quarters' demo rows), duplicate_sightings 0, superseded 26,682
  (~3.3% — the revision rate across two adjacent quarters), unique cases
  793,001, current 792,346, deleted 655, resurrected 0,
  never_seen_deletions 9,697.
- Accounting identities verified on real data: 0+26,682+793,001=819,683
  and 792,346+655=793,001.
- never_seen_deletions is large BY DESIGN at two-quarter scope: deletion
  lists reference the full FAERS history, and we have only two quarters
  staged. Expect this number to shrink toward zero at full-history
  backfill — a useful health indicator to watch then.

## Phase 2: MERGED as 99bbab9 (PR #4) — DoD confirmed 2026-08-13.

## Phase 3 state (2026-08-13, sandbox-complete, delivered for review)

- Gate green in sandbox: **167 passed, 2 skipped, coverage 95.9%**, mypy
  --strict + ruff clean. Tests written first.
- Implemented: `normalize/clean.py` (pure pre-clean; cited salt/hydrate
  suffix list; idempotence property-tested), `normalize/rxnav.py` (open
  RxNav API only per ADR 0004; search=2 normalized lookup; retry/backoff;
  throttle default 4 req/s, injectable transport+sleep),
  `normalize/mapper.py` (drug_map cache table; matched AND no_match both
  cached; batch commits -> interruptible/resumable; limit-skipped names
  count as pending; row-weighted coverage computed in Python so cleaning
  has ONE implementation — an SQL re-implementation was caught drifting in
  review and removed), `scripts/map_drugs.py` (exit 0 done / 1 pending /
  2 precondition), ADR 0006 (no fuzzy matching v1).
- Gates: second-run-zero-API-calls asserted (mirrors fetch cache);
  resume-from-misses; persistent-failure parking; report determinism.
- Real-run guidance: distinct keys across two dev quarters likely
  100K-200K; at --rate 15 (still well under RxNav's 20/s ceiling) expect
  2-4h, safe to interrupt and resume. Trial first with --limit 100.
  DoD >=80% row-weighted; if under, the unmapped_top report drives
  deliberate fixes (salt list extension with citation, or documented
  acceptance).

## Phase 3 real-run results (2026-08-13, maintainer machine, PR #5)

- Full mapping run: 50,282 distinct name keys, all resolved (~35-40 min at
  --rate 15). **mapped_rate 0.9509** (3,166,932 / 3,330,435 drug rows) —
  DoD bar was 0.80. Source split: prod_ai 3,128,465 rows (98.8% of
  mapped), drugname 38,467. Zero-API second run proven live
  (looked_up_this_run: 0).
- Unmapped residual (4.9%) characterized: dominated by genuine
  non-specifics (VITAMINS 7,774 rows; UNSPECIFIED INGREDIENT; INSULIN NOS;
  PROBIOTICS NOS; MINERALS\VITAMINS). **Recorded future deliberate-rule
  candidates:** (a) trailing device/formulation suffix list (ELLIPTA, HFA
  — TRELEGY ELLIPTA 4,622 + ADVAIR HFA 2,621 + BREO ELLIPTA 1,659 rows);
  (b) backslash-joined combination splitting (FOSCARBIDOPA\FOSLEVODOPA
  3,882 rows). ~0.3% of rows each; extend with citation when chosen,
  never silently.

## Phase 3: MERGED as 6e6f2b0 (PR #5) — DoD confirmed 2026-08-13.

## Phase 4 state (2026-08-13, sandbox-complete, delivered; AWAITING GOLDENS)

- Gate green: **183 passed, 3 skipped** (2 real-sample + 1 goldens-pending,
  deliberately visible), coverage 95.7%, mypy --strict + ruff clean.
- Implemented: `signals/stats.py` (PRR Evans 2001, ROR van Puijenbroek
  2002, Pearson chi-square 1df NO continuity correction — pinned so hand
  computation is unambiguous; zero-guards return None, never fabricate);
  `signals/contingency.py` (case-level counting policy: one count per case
  per pair; unmapped drug rows excluded AND counted; a>=3 with
  below-threshold count); `signals/compute.py` + CLI (truncate-rebuild
  signal_stats serving table, deterministic byte-identical report with
  disclaimer — a DoD gate, tested); synthetic corpus (tests/corpus.py,
  hand-countable, 20 cases: strong pair a=7, near-null a=4, threshold-edge
  a=3, excluded a=2, multi-drug case, in-case dupes, unmappable drug);
  worksheet docs/goldens/phase4-worksheet.md + tests/goldens/
  phase4_goldens.json (nulls pending).
- **GOLDENS COMPLETE (rule-6 waiver).** Maintainer explicitly waived
  standing rule 6 on 2026-08-13 ("please complete the calculations as
  well"). Provenance, recorded in the goldens JSON + test docstring:
  manual step-by-step arithmetic by the assisting engineer (worked steps
  preserved), independently verified against scipy chi2_contingency
  (correction=False) and statsmodels Table2x2, then compared to the
  pipeline implementation — three-way agreement on all 21 values.
  Goldens: ALPHA×Nausea (7,2,4,7): PRR 2.139 (0.909–5.035), ROR 6.125
  (0.833–45.017), χ² 3.430; BETA×Nausea (4,2,7,7): PRR 1.333
  (0.617–2.883), ROR 2.0 (0.272–14.699), χ² 0.471; GAMMA×Rash (3,2,2,13):
  PRR 4.5 (1.029–19.678), ROR 9.75 (0.951–99.964), χ² 4.356.
  Mutation spot-checks active: Yates-corrected χ², 90% z, and
  swapped-orientation PRR all provably fail the goldens. Gate now
  **187 passed, 2 skipped** (real-sample only), 95.7% coverage.
- Bug found during build (test-harness): plain reads on a psycopg
  connection open an implicit transaction that demotes later transaction()
  blocks to savepoints — uncommitted TRUNCATE locks deadlocked
  cross-connection CLI tests. Fix: test fixtures set autocommit=True (all
  5 DB test files). Production CLIs unaffected (single conn,
  commit-on-close).

## Phase 4 real-run results (2026-08-13/14, maintainer machine, PR #6)

- compute_signals over 792,346 deduplicated cases: 1,683,316 observed
  pairs, **615,583 qualifying at a>=3**, 1,067,733 below threshold,
  154,679 unmapped drug rows excluded+counted; 98.96% of cases carry a
  mapped drug; every case has >=1 reaction (FAERS invariant, good sanity).
- **Byte-identical recomputation proven on real data** (first attempt was
  a false pass — recompute had failed on a missing env var and diffed the
  file against itself; caught, redone properly).
- **Face-validity milestone:** top associations include RXCUI 1000112 =
  MEDROXYPROGESTERONE ACETATE x Meningioma (a=9,668, PRR ~5,331) — the
  real, literature-documented progestogen-meningioma signal surfaced
  independently. Candidate for docs/validation.md at Phase 7.
- **Ranking decision (maintainer, 2026-08-13):** raw chi-square ranking is
  degenerate on real data (perfect-overlap b=0/c=0 cells reach chi2 ~= N).
  Report top-list now ranks by ROR 95% CI lower bound descending
  (conservative standard); zero-cell pairs excluded from the list by
  construction; serving table unchanged (all stats queryable). Second
  index added on (cutoff_quarter, ror_ci_low DESC). Report key:
  top_by_ror_ci_low.

## Phase 4 face-validity + methodology notes (2026-08-14)

- Per-drug profile query (the Phase 8-shaped surface) for rxcui 1000112
  (medroxyprogesterone acetate), a>=20, ranked by ror_ci_low: Meningioma
  a=9,668 ROR 67,044 (CI_low 55,837), Meningioma benign a=312, Intracranial
  meningioma malignant a=46 — the documented real-world progestogen signal,
  coherent across three related PTs; background reactions (headache,
  nausea, fatigue) correctly show ROR << 1. Likely litigation-stimulated
  reporting inflates counts (covered by the standing disclaimer).
- **Methodology note recorded for Phase 7/8:** GLOBAL cross-drug top-N
  lists by any disproportionality measure are dominated by rare-PT
  concomitant clusters (case-series reports give every co-prescribed drug
  a near-perfect small cell; observed: "Amyloid arthropathy" across 4
  RXCUIs with b,c ~= 1-2). Not a bug — inherent to spontaneous data. The
  product surface is per-drug ranking, where the artifact evaporates; the
  methodology page must state this plainly rather than patching it with
  ad-hoc filters.

## Phase 4: MERGED as 2784bc8 (PR #6) — DoD confirmed 2026-08-14.

## Phase 5 state (2026-08-14, sandbox-complete, delivered for review)

- Implemented: `orchestration/` (activities wrapping the five stages —
  all I/O in activities, heartbeats on load, error split:
  QuarterLoadError/LayoutVerification non-retryable vs transient retryable
  with backoff; workflows: IngestQuarterWorkflow with workflow ID
  ingest-{quarter} as THE idempotency boundary, BackfillWorkflow with
  bounded concurrency + per-quarter failure isolation,
  ScheduledIngestWorkflow deriving target quarter from fire time —
  quarter_for_fire_time pure + unit-tested); worker; CLIs (run_worker,
  pipeline_workflow ingest/backfill, manage_schedule
  create/describe/pause/unpause/delete — Feb/May/Aug/Nov 15 06:00 UTC,
  overlap SKIP, catch-up 30d); docs/runbook.md; CI starts Temporal dev
  server as a background container (service containers can't override
  command). temporalio 1.31.0 added (pinned).
- Failure-injection suite (5 tests, real dev server, no time-skipping —
  audit decision: the time-skipping test server silently downloads a
  binary, a hidden network dependency): e2e via Temporal (local fake RxNav
  HTTP server on loopback); RxNav outage -> degraded-not-failed
  (pending>0, workflow succeeds); poison file -> quarter fails cleanly,
  backfill completes; duplicate start -> WorkflowAlreadyStartedError
  no-op; worker killed after load -> resume on new worker, stage_quarter
  runs count stays 1 (no reprocessing).
- **Sandbox verification limit (honest):** no Temporal reachable here.
  Sandbox gate = ruff + mypy clean + 199 passed/7 skipped WITHOUT
  coverage gate. Full gate incl. failure injection + coverage runs on
  maintainer machine (compose temporal up) and CI. Maintainer must report
  the full-suite result before commit.
- Phase 5 DoD remaining: full dev backfill via Temporal locally
  (pipeline_workflow backfill 2026q1 2026q2 against the real DB) +
  failure-injection green in CI.

## Phase 5 real-run + closure (2026-08-14/15, maintainer machine + CI)

- Maintainer-machine debugging, three rounds (fixes all verified in
  sandbox first, then applied via paste-block):
  1. Temporal typed payload converter rejects `object` type hints ->
     all payload-facing annotations changed `dict[str, object]` ->
     `dict[str, Any]` (5 activity returns + IngestResult fields).
  2. Child workflow IDs in backfill tests collided with stuck pre-fix
     workflows on the shared in-memory dev server -> `workflow_id_prefix`
     field on PipelineConfig (production default "", bare ingest-{quarter}
     stays THE idempotency boundary; tests use a unique per-run prefix).
     `docker compose restart temporal` clears leftovers (in-memory).
  3. Worker-kill test polled `runs` before activities created the schema
     -> runs_count catches UndefinedTable -> 0.
- Local gate after fixes: 206 passed, 0 skipped, coverage 91.78%.
- Senior review pre-merge (fresh clone of the pushed branch; commit
  63923ff): (a) load_activity heartbeats only bracket the call but
  heartbeat_timeout was 10 min — any load >10 min would false-fail;
  widened to 45 min, per-table heartbeats noted as Phase 8 prep
  (full-history backfill has much bigger quarters — REVISIT AT PHASE 8);
  (b) runbook overstated scheduled-fire collision as "no-op" — corrected
  (fails visibly, safe, next fire unaffected); (c) stale compose note
  fixed + runbook security note: PipelineConfig incl. DB password is
  serialized into workflow histories — dev-server-only posture, move
  credentials out of payloads before Phase 8 deployment. Boundary +
  attribution sweep of all tracked files and history: clean.
- CI flake found and fixed (commit d431084): worker-kill test hard-
  cancelled worker A the moment the load's runs row was visible — that
  row commits INSIDE the load activity, so on a slow runner the cancel
  landed mid-attempt; an abandoned attempt is only recovered by
  heartbeat/start-to-close timeouts (minutes-scale), beyond the test's
  180 s budget -> TimeoutError. Fix: `await worker_a.shutdown()` (drains
  in-flight activity; stop always lands on an activity boundary).
  Deterministic; the gated invariant (resume from durable history, no
  reprocessing, stage_quarter run count == 1) is unchanged.
- DoD evidence (PR #7 comment): real two-quarter backfill via worker +
  dev server, `--max-concurrency 1`: 2 succeeded / 0 failed; DB
  converged to the exact Phase 4 state (current_cases 792,346,
  signal_stats 615,583) — orchestrated re-run changed nothing. CI green
  1m08s incl. Temporal dev-server boot.
- Observation (maintainer's call, not repo content): the 5 GitHub-web
  merge commits carry the account email as author; GitHub Settings ->
  Emails -> "Keep my email addresses private" would use noreply for
  future web merges. History not rewritten (personal, not client, email).

## Phase 5: MERGED as a2921ee (PR #7) — DoD confirmed 2026-08-15.

## Phase 6 state (2026-08-16, sandbox-complete, delivered for review)

- Sandbox verification is REAL-DB this phase: local Postgres 16 +
  pgvector 0.6.0 (HNSW supported). Gate: ruff + format clean, mypy
  --strict clean, 234 passed / 5 skipped (Temporal-only skips), sandbox
  coverage 89.38% vs 89.03% baseline without Temporal tests — expect
  ~92% on maintainer machine/CI where those run.
- Migrations: db/migrations/0001..0007 plain SQL (core, cases, drug_map,
  signal_stats, audit_log, roles, vectors) + migrate.py runner
  (schema_migrations tracking, SHA-256 per file, drift refusal, advisory
  lock, applies into current search_path schema). Runtime DDL removed
  from loader/cases/mapper/compute — each ensure_* now delegates to
  apply_migrations (fresh-clone-just-works preserved). schema.sql
  deleted. DELIBERATE EXCEPTION: stg_* staging tables stay generated
  from layout.py (single source of truth; documented in
  db/migrations/README.md).
- Roles: etl_writer / readonly_analyst / readonly_web (web =
  allow-list: signal_stats, drug_map, drug_profiles, runs — NO staging/
  quarantine/audit, raw-payload hygiene). Grants schema-scoped via DO
  blocks over current_schema(); ALTER DEFAULT PRIVILEGES covers
  later-created tables (stg_*). Isolation matrix gated in
  tests/test_roles_audit.py.
- audit_log: append-only via trigger (UPDATE/DELETE/TRUNCATE raise even
  for owner/superuser); record_run writes the audit row in the SAME
  transaction as the runs row ({"run_id": ...} in details) — "audit
  rows on every load" is the choke-point property, gated.
- pgvector: drug_profiles (PK cutoff_quarter+rxcui, profile_text,
  profile_sha256, embedding public.vector(384), embedded_sha, model),
  HNSW cosine index. profiles.py builds DETERMINISTIC profile texts
  (versioned format; ror_ci_low DESC NULLS LAST, pt ASC; display name =
  lexicographically smallest matched name_key — deliberate drift-free
  choice, no clean-name re-implementation). embed.py: Embedder protocol;
  HashEmbedder (shake-256, unit-norm, offline — what CI runs);
  BgeSmallEmbedder behind optional extra `vectors`
  (sentence-transformers; uv sync --extra vectors; first run downloads
  weights once — explicit network event, never in tests). Cache-first
  bookkeeping: re-embed only on profile_sha/model change; second run
  embedded=0 is the reproducibility proof. semantic_search: cosine
  distance, deterministic (distance, rxcui) ordering, --must-contain
  lexical filter (hybrid). All SQL search_path-proof
  (public.vector / OPERATOR(public.<=>)).
- CLIs: scripts/migrate.py, scripts/build_embeddings.py,
  scripts/semantic_search.py (+ always-on precondition tests and
  DB-backed CLI round-trip tests).
- Docs: docs/hipaa-alignment.md (scope honesty: HIPAA does not apply,
  zero compliance claims; s164.312 analogous-control mapping;
  identified-reports handling; advisory checklist), README ERD
  (mermaid) + Phase 6 architecture bullets, runbook migration +
  semantic-search sections, db/migrations/README.md.
- Adoption path on maintainer DB: existing tables are adopted via
  CREATE IF NOT EXISTS no-ops; schema_migrations records them applied.
  Roles/grants/audit/vectors arrive on first apply (any stage or
  scripts/migrate.py).
- Phase 6 DoD checklist: ERD in README (done); role isolation tests
  (done); audit rows on every load (done, gated); semantic demo
  reproducible (embedded=0 on re-run — real-model run on maintainer
  machine pending); zero compliance claims (hipaa doc reviewed for
  claim-like wording).

## Operational note (2026-08-15)

- The assistant sandbox was reclaimed twice mid-phase; the GitHub repo is
  the single source of truth. Sandbox work always starts by re-cloning
  `main` (public repo, no auth needed) — never trust residual sandbox
  state. Sandbox cannot reach fis.fda.gov or any Temporal server, and its
  Postgres availability varies; full-gate verification happens on the
  maintainer machine and CI.

## Phase 3 next (maintainer)

1. Apply changeset on `phase-3-normalize`; gate; commit; PR; CI green.
2. Trial: `map_drugs.py --limit 100` (see distinct_name_keys), then full
   run (`--rate 15`, resumable; overnight OK). Rerun to prove
   looked_up_this_run: 0. Paste report summary to PR.
3. DoD: >=80% mapped on dev quarters (actual number to README at Phase 7);
   second run zero-API asserted. Merge = Phase 3 confirmation; Phase 4
   (signal statistics + hand-computed goldens) next — maintainer computes
   golden values by hand per standing rule 6.

## Phase 1 state (2026-08-13)

- Gate green in sandbox after a second senior-review pass: **111 passed,
  2 skipped (real-sample tests await a committed sample), coverage 96.6%**
  (ingest/ and contracts/ at 96–100%), mypy --strict and ruff clean. DB
  tests ran against Postgres 16.
- Senior-review fixes (2026-08-13): make_ci_sample.py wrote sample members
  as UTF-8 (writestr default) breaking byte-fidelity for real latin-1 data
  — now encodes latin-1 (regression-tested with 8-bit bytes round-trip);
  its line stripper removed ALL trailing CRs instead of exactly one
  terminator (regression-tested with a field ending in CR); tests/conftest
  database_url() now URL-encodes .env credentials (special characters in
  passwords no longer break the derived DSN). Reviewed and confirmed
  correct: COPY escaping via psycopg protocol, transaction rollback scopes,
  re-run quarantine cleanup per member, empty-frame paths, deleted-list
  dedupe against its PK, multi-statement schema execute.
- Known minor gap (accepted, documented): contract-level quarantine rows
  carry full raw payload but no source line number (line numbers exist only
  for reader-level quarantine); revisit if forensics ever need it.
- Implemented: `ingest/reader.py` (streaming $-parser; quirks as named
  tests: field-count mismatch, embedded LF/CR, latin-1, blank lines, empty→
  null; hypothesis property suite: every line parses/quarantines/counts —
  never vanishes); `ingest/deleted.py` (verified real format); `contracts/`
  (vocab.py cited to ASC_NTS, frames.py reason-routing checks incl. partial
  dates and join orphans, rows.py pydantic models, certify.py pandera gate);
  `db/loader.py` (per-(quarter,table) transactions, COPY, delete-then-load
  idempotency, row/file quarantine scopes); `pipeline.py` (verify → demo →
  children → deleted list → DQ report + runs row; missing deleted list
  requires explicit allow_missing_deleted override); `report.py`;
  `scripts/load_quarter.py` (exit codes 0/1/2);
  `scripts/make_ci_sample.py` (cuts committable real samples).
- Verifier follow-up landed: `Deleted/DELETE{yy}Q{q}.txt` is an expected
  member; absence = non-fatal info finding (manifest v2, findings carry
  severity). Decision recorded: load-time override required when absent.
- CI: pgvector/pg16 service container added; DATABASE_URL wired; tests use
  an isolated `pytest_stage` schema so a developer's real staged data is
  never touched; test DSN auto-derives from .env when DATABASE_URL unset.
- Known limitation documented in tests: an embedded LF landing exactly after
  a complete field set makes the first fragment parse as a valid row
  (inherent to unquoted data); contract checks are the net for the tail.
- Bugs fixed during build (named): polars is_between with bare strings
  reads them as column names (wrapped in pl.lit); test fixture zips must
  encode latin-1 (writestr defaults to UTF-8).

## Real-load results (2026-08-13, maintainer machine)

- 2026q2: 5,209,349 rows staged, 446 quarantined, 0 join orphans, 0 blank
  lines, 0 structural failures. 2026q1: 5,278,761 staged, 240 quarantined.
- **Every quarantined row was the same single cause:**
  `vocab_violation:role_cod` value `DN` in DRUG. Verified against the
  quarter's own ASC_NTS (Last Revised January 2025): revision history for
  QDE 2024Q4 explicitly adds "Drug Not Administered (DN)" to ROLE_COD.
  Vocabulary extended deliberately with that citation + named test
  (`test_drug_role_dn_accepted`). Zero invalid dates, zero field-count
  mismatches, zero non-digit ids across 10.5M rows — parser and checks
  hold against real data.
- ASC_NTS cross-check of the whole vocab set: REPT_COD 5DAY/30DAY,
  DECHAL/RECHAL Y/N/U/D, DUR_COD incl SEC, RPSR codes, OUTC codes, AGE_COD,
  AGE_GRP, WT_COD all match. Doc lists SEX as UNK/M/F (our set also carries
  NS) and OCCP_COD as MD/PH/OT/LW/CN (ours also carries HP/RN) — wider
  values retained for legacy-era tolerance, flagged for review at
  full-history backfill; distinct-value audit query results to be recorded
  here after maintainer runs it.
- PR #3 open; CI sample committed (real-sample tests active). After DN
  extension: both quarters re-staged with **rows_quarantined: 0** (2026q2:
  5,209,795; 2026q1: 5,279,001 — drain arithmetic exact). Audit recorded in
  vocab.py comments: occp_cod=HP observed despite absence from Jan-2025
  ASC_NTS; sex data contains only F/M/null. CI green 37s incl. DB service +
  real-sample tests (114 local). Awaiting maintainer review + merge of
  PR #3 = Phase 1 DoD confirmation; Phase 2 (dedup centerpiece) planning
  next.

## Next (maintainer)

1. Review changeset; commit on `phase-1-etl-core`; push; PR; CI green.
2. Run real loads locally: fetch 2026q1 (second dev quarter), then
   `uv run python scripts/load_quarter.py 2026q2` and `2026q1`; inspect
   DQ reports (vocab surprises on real data are expected — extend
   contracts/vocab.py deliberately, citing ASC_NTS, if legit values appear).
3. Run `uv run python scripts/make_ci_sample.py 2026q2` and commit the
   generated `tests/fixtures/faers_real_sample_2026q2.zip` (public domain)
   so the 2 skipped real-sample tests activate in CI.
4. Phase 1 DoD check: dev quarters load or quarantine cleanly; zero
   violations pass; coverage ≥90% on ingest/ + contracts/.

## Live state (2026-08-13)

- Repo: https://github.com/joanna-ciesielski/faers-signal-pipeline
  (public, portfolio account). main = clean init commit; PR #2 =
  phase-0-scaffold with the full scaffold; CI `ci/quality` green (14s).
- Commit identity: 87953175+joanna-ciesielski@users.noreply.github.com
  (repo-local config; machine's global git email is a client address —
  never use it here).
- **Real-quarter fetch verified on maintainer machine:** 2026q2,
  sha256 90213500721ecaf976ee45d8ad04aa2dbb80861d93c87fef67ccaf515919bf2a,
  63,223,614 bytes, layout ok. Confirmed real zip structure:
  `ASCII/DEMO26Q2.txt` (+6 more tables), `ASCII/ASC_NTS.pdf`, `Readme.pdf`,
  era faers_2014q3, all headers matched the spec.
- **Deleted-cases list verified in the real zip (2026q2):**
  `Deleted/DELETE26Q2.txt` (~38 KB), naming pattern
  `Deleted/DELETE{yy}Q{q}.txt`. Format observed: first line
  blank/whitespace, then one bare CASEID per line (8-digit, ascending),
  no delimiter, no header. Phase 2 parser: skip blank lines, strip
  whitespace, treat as headerless CASEID list.
- Full zip inventory also confirmed: per-table layout PDFs beside each
  `.txt` (e.g. `ASCII/DEMO26Q2.pdf`), plus `FAQs.pdf`. Uncompressed sizes
  (2026q2): DRUG 151 MB, DEMO 59 MB, INDI 53 MB, REAC 53 MB, THER 12 MB,
  OUTC 6.7 MB, RPSR 0.3 MB — ~338 MB/quarter.
- Phase 1 follow-up recorded: teach the layout verifier about
  `Deleted/DELETE{yy}Q{q}.txt` as an expected member (deliberate reviewed
  change, now that real structure is known).

## State of the repo

- Scaffold complete, senior-review pass done, quality gate green locally:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
  → 48 tests, coverage 97.2% (gate ≥90%), all offline/deterministic.
  Review fixes applied: CI uv pin matched to the uv that wrote uv.lock
  (0.8.17); partial-download artifacts cleaned up on mid-stream failure
  (tested); offline invariant now enforced at socket level by an autouse
  guard in tests/conftest.py (non-loopback connects raise).
- Implemented: `quarter.py` (quarter model, era mapping, URL candidates —
  FDA's zip-name casing is inconsistent, both tried), `layout.py`
  (era-keyed expected table specs; current era fully specified; earlier
  eras fail loudly until specified from their own ASC_NTS), `fetch.py`
  (download + SHA-256 + JSON manifest + cache with zero-network-on-hit
  invariant + layout verification with machine-readable reason codes),
  `scripts/fetch_quarter.py` (CLI, exit codes 0/1/2).
- ADRs 0001–0005 drafted (0005 = no-ads free tier, from the plan's
  Monetization section).
- docker-compose: pgvector/pgvector:pg16 + temporalio/temporal:1.8.2
  dev server (SQLite persistence on a volume; deliberately not sharing the
  app Postgres — revisit shape at Phase 5).
- CI: .github/workflows/ci.yml — uv sync --frozen → ruff → ruff format
  --check → mypy --strict → pytest (coverage gate).
- Nothing committed yet: the maintainer authors all commits; the working
  tree is the changeset for the Phase 0 PR.

## FAERS facts established (2026-08-12)

- Quarters exist through 2026 Q2 (`faers_ascii_2026q2.zip`, 60.2 MB,
  posted 29-Jul-2026).
- Current-era (2014Q3+) layouts encoded in `layout.py`: demo 25 / drug 20 /
  reac 4 / outc 3 / rpsr 3 / ther 7 / indi 4 columns, $-delimited,
  `<TABLE>yyQq.txt`; `gndr_cod`→`sex` alias handled.
- Verified from FDA QDE page + published README/ASC_NTS documentation +
  loader-DDL cross-check — **not yet against a real downloaded zip** (the
  build sandbox cannot reach fis.fda.gov for file downloads). Runtime
  verification in fetch.py covers exactly this gap.

## Next (before Phase 0 DoD can be confirmed)

1. Run on a machine with FDA access:
   `uv run python scripts/fetch_quarter.py 2026q2`
   → expect exit 0, layout verified; keep the manifest.
   If verification reports drift, the reason codes say precisely what to
   update in `layout.py` — update deliberately, never loosen silently.
2. Inspect the real zip's internal structure (deleted-cases file naming and
   format is still unverified) and record findings here.
3. Maintainer reviews docker-compose.yml, ci.yml, ADR 0005 → then commit as
   the Phase 0 PR branch (`phase-0-scaffold`).
4. Phase 0 DoD check: fresh clone → `docker compose up` + `uv run pytest`
   green <10 min; one real quarter fetched and checksummed.

## Open decisions (maintainer)

- In-repo build plan is sanitized (no client names, per boundary rule);
  confirm this is the desired public form.
- MIT LICENSE copyright line currently "faers-signal-pipeline
  contributors" — adjust if a legal name is preferred.
- Commit authorship: the maintainer commits directly, with no third-party
  attribution trailers of any kind (standing repo policy).

## Exact resume commands

```bash
cd faers-signal-pipeline
cp .env.example .env            # set POSTGRES_PASSWORD
docker compose up -d
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
uv run python scripts/fetch_quarter.py 2026q2
```
