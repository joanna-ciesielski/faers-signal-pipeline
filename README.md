# faers-signal-pipeline

A public pharmacovigilance data platform: Python 3.12 ETL over FDA FAERS
quarterly extracts, orchestrated with Temporal (quarterly Schedule +
backfill), landing in PostgreSQL 16 + pgvector, computing PRR/ROR
disproportionality statistics behind a CI quality gate — later published as a
free, read-only web explorer.

> **Status: Phase 0 (scaffold & data acquisition).** Nothing here is a
> finished analysis. See `docs/plans/build-plan.md` for the phased plan.

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
uv run pytest               # offline; green in well under 10 minutes
uv run python scripts/fetch_quarter.py 2026q2   # fetch + checksum + verify one quarter
```

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

## Architecture (Phase 0 snapshot)

- `src/faers_signal_pipeline/` — library code. Currently: quarter/era model
  (`quarter.py`, `layout.py`) and download/checksum/layout-verification
  (`fetch.py`). Layouts are **verified against every downloaded quarter** —
  FAERS layouts drift across eras, so the expected schema is data, not
  assumption.
- `scripts/fetch_quarter.py` — CLI wrapper; exit codes distinguish
  "verified", "layout drift detected" and "download failed".
- `docs/adr/` — architecture decision records, including the licensing and
  no-ads decisions.

Quality bar (CI-enforced from day one): `ruff` (lint + format),
`mypy --strict`, `pytest` with coverage ≥ 90%, all tests offline and
deterministic.

## License

MIT — see `LICENSE`. (The license covers this code; FAERS data is public
domain; terminology licensing is documented above.)
