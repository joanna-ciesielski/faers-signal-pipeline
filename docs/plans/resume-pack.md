# Resume pack

> Assume zero context. Read `docs/plans/build-plan.md` first; its Fixed
> Decisions, Monetization decisions, and Boundary Rules are binding. The
> authoritative (unsanitized) plan is the maintainer's private Drive doc
> "Build Plan B v3 — FAERS Signal Pipeline + Live Explorer Service (FINAL)".

- Updated: 2026-08-13
- Current phase: **2 — Case versioning & deduplication (implemented +
  senior-reviewed in sandbox; delivered for maintainer review; not
  committed)**. Phase 0 merged as bc8e449 (PR #2); Phase 1 merged as
  e6bfe07 (PR #3) — both DoD-confirmed. Dev quarters 2026q1+2026q2 staged
  with zero quarantine.

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
