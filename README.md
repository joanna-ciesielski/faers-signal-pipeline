# faers-signal-pipeline

A public pharmacovigilance data platform: Python 3.12 ETL over FDA FAERS
quarterly extracts, orchestrated with Temporal (quarterly Schedule +
backfill), landing in PostgreSQL 16 + pgvector, computing PRR/ROR
disproportionality statistics behind a CI quality gate — later published as a
free, read-only web explorer.

> **Status: Phase 3 (drug normalization).** Nothing here is
> a finished analysis. See `docs/plans/build-plan.md` for the phased plan.

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

## Quickstart

```bash
cp .env.example .env        # set a local Postgres password
docker compose up -d        # PostgreSQL 16 + pgvector, Temporal dev server
uv sync
uv run pytest               # loopback-only; DB tests use the compose Postgres
uv run python scripts/fetch_quarter.py 2026q2   # fetch + checksum + verify one quarter
export DATABASE_URL="postgresql://faers:YOUR_PASSWORD@127.0.0.1:5432/faers"
uv run python scripts/load_quarter.py 2026q2    # parse -> validate -> stage + DQ report
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

## Architecture (Phase 1 snapshot)

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
- `docs/adr/` — architecture decision records, including the licensing and
  no-ads decisions.

Quality bar (CI-enforced from day one): `ruff` (lint + format),
`mypy --strict`, `pytest` with coverage ≥ 90%, all tests offline and
deterministic.

## License

MIT — see `LICENSE`. (The license covers this code; FAERS data is public
domain; terminology licensing is documented above.)
