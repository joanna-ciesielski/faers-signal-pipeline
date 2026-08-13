# Resume pack

> Assume zero context. Read `docs/plans/build-plan.md` first; its Fixed
> Decisions, Monetization decisions, and Boundary Rules are binding. The
> authoritative (unsanitized) plan is the maintainer's private Drive doc
> "Build Plan B v3 — FAERS Signal Pipeline + Live Explorer Service (FINAL)".

- Updated: 2026-08-12
- Current phase: **0 — Scaffold & data acquisition** (in review, not merged)

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
