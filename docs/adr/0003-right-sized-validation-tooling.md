# ADR 0003 — Right-sized tooling: Python 3.12, uv, ruff, mypy --strict, pytest, pydantic v2 + pandera, Polars

- Status: accepted
- Date: 2026-08-12

## Context

FAERS quarters run to millions of $-delimited rows with era-dependent
layouts and well-known quirks. The credibility of the pipeline rests on
typed contracts, deterministic outputs, and a CI gate — not on cluster-scale
tooling.

## Decision

Python 3.12 managed by uv; ruff + mypy --strict + pytest (coverage ≥90%
where the plan specifies); pydantic v2 for row/record contracts; pandera for
frame-level checks; Polars for large delimited files.

## When the rejected tools would win

- **Spark**: data that no longer fits one machine, or an existing cluster.
- **dbt**: many SQL-first analysts collaborating on transform DAGs.
- **Great Expectations**: cross-team data-contract documentation as a
  product; here pandera + pydantic express the same checks in-code.
- **pandas**: swap noted if an integration needs its ecosystem; Polars is
  faster and stricter for this shape of work.
