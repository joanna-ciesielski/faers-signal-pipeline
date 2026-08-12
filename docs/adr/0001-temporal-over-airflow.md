# ADR 0001 — Temporal (with Schedules) over Airflow

- Status: accepted
- Date: 2026-08-12

## Context

FAERS publishes quarterly. Ingestion is therefore recurring by nature, needs
durable multi-step execution (fetch → parse → validate → load → dedup →
normalize → signal refresh), per-step retries with backoff, idempotent
re-runs, and a first-class backfill story over ~20 years of quarters.

## Decision

Temporal, using **Temporal Schedules** for the quarterly trigger and a
parent workflow with bounded concurrency for backfill. Workflow-as-code with
the time-skipping test framework makes the failure-injection suite (Phase 5)
an ordinary pytest concern.

## Consequences

- Orchestration state lives in Temporal's own persistence (dev server
  locally), separate from domain data in PostgreSQL.
- Activities must be idempotent; idempotency keys are
  (quarter, code version, config hash).

## When Airflow would win

A calendar-driven batch estate with many heterogeneous DAGs, an existing
Airflow operations team, or heavy reliance on its provider/operator
ecosystem. For a single recurring durable pipeline, a scheduler-first tool
adds operational surface without adding durability semantics.
