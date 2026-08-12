# ADR 0002 — One storage engine: PostgreSQL 16 + pgvector, precomputed serving tables

- Status: accepted
- Date: 2026-08-12

## Context

The platform needs relational integrity (case versioning, lineage,
quarantine), analytical outputs (signal statistics), and semantic search
(drug safety-profile embeddings). It must later serve a public read-only
explorer within a $30/month operating ceiling.

## Decision

A single PostgreSQL 16 instance with the pgvector extension. Signal
statistics are **precomputed at ingest into indexed serving tables**; the
public site performs cheap indexed reads only — no per-request analytics.

## Consequences

- One backup/restore/security story; least-privilege roles
  (`etl_writer`, `readonly_web`, `readonly_analyst`) in one engine.
- Precomputation is what makes the cost ceiling realistic.

## When alternatives would win

A dedicated vector store (FAISS/Chroma/Qdrant) at embedding scale far beyond
one drug-profile row per drug; a warehouse (BigQuery/Snowflake) if
per-request analytics over billions of rows were the product. Neither is.
