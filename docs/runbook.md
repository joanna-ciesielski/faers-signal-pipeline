# Pipeline runbook (Temporal orchestration)

All commands assume the compose stack is up (`docker compose up -d`) and
`DATABASE_URL` is exported. The Temporal Web UI is at http://localhost:8233.

## Schema migrations

```bash
uv run python scripts/migrate.py    # idempotent; safe any time
```

Every pipeline stage also applies pending migrations defensively, so a
fresh clone works without this step — run it explicitly when you want
schema changes applied at a moment you choose (e.g. before a backfill).
An edited already-applied migration file is refused (checksum drift);
schema changes are always new files. See `db/migrations/README.md` for
the role model and the staging-table exception.

## Semantic search over drug profiles

```bash
uv sync --extra vectors            # once: installs sentence-transformers
uv run python scripts/build_embeddings.py     # builds profiles + embeds
uv run python scripts/semantic_search.py "progestogen meningioma risk"
uv run python scripts/semantic_search.py "hair loss" --must-contain Alopecia
```

First `build_embeddings` run downloads bge-small-en-v1.5 weights once
(explicit network event; cached under `~/.cache`). Re-runs embed only
profiles whose text changed — an unchanged database prints
`embedded=0`, which is the reproducibility proof. The `--embedder stub`
variant exists for offline demos and is what CI exercises.

## Normal operation

```bash
uv run python scripts/run_worker.py                 # terminal 1: the worker
uv run python scripts/pipeline_workflow.py ingest 2026q2   # terminal 2
```

The workflow ID is `ingest-<quarter>`. Starting a quarter that is already
running is rejected by Temporal and reported as a no-op — this is the
duplicate-fire idempotency boundary, by construction.

## Quarterly schedule

```bash
uv run python scripts/manage_schedule.py create     # once
uv run python scripts/manage_schedule.py describe   # next fire times
uv run python scripts/manage_schedule.py pause      # e.g. before maintenance
uv run python scripts/manage_schedule.py unpause
```

Fires 15 Feb / 15 May / 15 Aug / 15 Nov, 06:00 UTC (~2–3 weeks after FDA
posts the prior quarter). Overlap policy SKIP: a still-running ingest
suppresses a new fire. Catch-up window 30 days: fires missed while the
worker was down still run when it returns within the window. The target
quarter is derived deterministically from fire time
(`quarter_for_fire_time`, unit-tested).

## Backfill

```bash
uv run python scripts/pipeline_workflow.py backfill 2025q1 2025q2 2025q3 2025q4 --max-concurrency 2
```

Quarters run oldest-first with bounded concurrency. One quarter's failure
(e.g. a poison file) is recorded in the summary; the batch completes. Order
does not matter for correctness — the dedup merge is order-independent by
construction (Phase 2 gate) — concurrency is purely a throughput knob.
Quarters predating the Deleted/ folder need `--allow-missing-deleted`
(the recorded override; see docs/dedup-policy.md). That includes the
whole 2012Q4-2014Q2 era AND the legacy AERS era (2004Q1-2012Q3): real
archives from both were inspected and ship no deleted-cases lists at
all, so a historical backfill passes the flag for those ranges.

## Failure semantics (what the failure-injection suite proves)

- **Worker killed mid-quarter:** history is durable; a restarted worker
  resumes at the first unfinished activity. Completed activities are never
  re-run; an in-flight one retries, and every activity is idempotent at
  the DB level (delete-then-load, truncate-rebuild, cache-first), so a
  retry never double-processes.
- **Poison file / verification failure:** non-retryable — the quarter
  fails cleanly with the reason in the workflow result; nothing loads
  partially (Phase 1 transactional semantics).
- **RxNav outage:** the mapper retries with backoff, then parks failing
  names and the quarter completes *degraded* — `pending_lookups` in the
  result says how many. Re-running the ingest (or `map_drugs.py`) later
  picks up exactly the parked names (cache-first).
- **Duplicate schedule fire:** overlap policy SKIP at the schedule
  level — a still-running scheduled ingest suppresses the next fire
  entirely. The workflow-ID boundary also rejects a scheduled start
  that collides with a manually started ingest of the same quarter;
  that scheduled run then fails visibly in the Web UI (safe: no
  double-processing, and the next quarterly fire is unaffected).

## Inspecting and replaying

- Web UI (http://localhost:8233): every workflow's event history — inputs,
  each activity's attempts, backoffs, and results.
- CLI equivalent: `docker compose exec temporal temporal workflow show
  --workflow-id ingest-2026q2`.
- A failed quarter, once the cause is fixed, is simply re-run:
  `pipeline_workflow.py ingest <quarter>` — idempotency makes it safe.
- The dev server keeps history in memory: a compose restart clears
  workflow history (not pipeline data — that lives in Postgres). Durable
  Temporal persistence is a deliberate Phase 5+ deferral; revisit before
  Phase 8 deployment.

## Security note (dev server)

`PipelineConfig` — including `DATABASE_URL` with its password — is
serialized into workflow histories and into the schedule definition on
the Temporal server. That is acceptable only for the local single-user
dev server. Before any shared or production Temporal deployment
(Phase 8), credentials move out of workflow payloads: environment or
secret store on the worker, or a payload codec.

## Log hygiene

Activities log stage progress and counts only — never raw FAERS records
(standing rule; same posture the live service inherits in Phase 8).
