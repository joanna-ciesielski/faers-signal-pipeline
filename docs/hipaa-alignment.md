# HIPAA alignment (scope honesty first)

## What this document is — and is not

**HIPAA does not apply to this project, and this project claims no HIPAA
compliance.** FAERS quarterly extracts are published by the US FDA as
public-domain data. This repository is not a covered entity, not a
business associate, and processes no protected health information (PHI)
as defined by 45 CFR §160.103. Nothing here has been assessed, audited,
or certified against any regulatory framework, and nothing here should
be read as a compliance claim of any kind.

What this document IS: a demonstration that the platform's storage and
access design is *informed by* the technical-safeguard vocabulary of
HIPAA's Security Rule (45 CFR §164.312) — the discipline a
health-adjacent data platform should exhibit even when the rule itself
does not bind it. The mapping below says "here is the analogous control
and where it lives in this codebase", never "this satisfies the
requirement".

## Why care at all, if the data is public?

Two honest reasons:

1. **Identified-reports reality.** FAERS case reports are de-identified
   by FDA before publication, but the extracts still carry demographic
   fields (age, sex, country, event dates), and FDA's own documentation
   acknowledges that free-text fields have occasionally contained
   inadvertently identifying details. The correct posture is to treat
   raw report payloads as *sensitive by default*: the public serving
   tier of this platform exposes only aggregated statistics
   (`signal_stats`, `drug_profiles`), never raw report rows, and the
   `readonly_web` role is technically unable to read staging or
   quarantine tables (which hold raw lines). De-identified public data
   is handled as carefully as if it weren't.
2. **Portfolio honesty.** This project's professional context is
   health-data engineering, where §164.312 is the shared vocabulary for
   "did you think about access, audit, and integrity?". Designing to
   that vocabulary — and saying plainly that no certification is
   claimed — demonstrates both the skill and the scope honesty.

## §164.312 technical safeguards — analogous controls here

| §164.312 safeguard | Analogous control in this platform |
|---|---|
| (a) Access control | Three cluster roles with least privilege: `etl_writer` (pipeline DML; cannot mutate audit history), `readonly_analyst` (read-everything, write-nothing), `readonly_web` (explicit allow-list: `signal_stats`, `drug_map`, `drug_profiles`, `runs` — no staging, no quarantine, no audit). Enforced by grants in `db/migrations/0006_roles.sql` / `0007_vectors.sql`; gated by `tests/test_roles_audit.py`. |
| (b) Audit controls | Append-only `audit_log`: every recorded pipeline run writes an audit row in the same transaction (`record_run`); UPDATE/DELETE/TRUNCATE are blocked by trigger for every role including the table owner (`0005_audit_log.sql`); gated by tests. |
| (c)(1) Integrity | Downloaded archives are SHA-256-verified against a manifest; layout is verified against the era spec before any load; contract violations are quarantined with machine-readable reasons, never silently dropped or repaired; migration files are checksummed and immutable once applied (drift refuses to proceed). |
| (d) Person or entity authentication | Postgres role-based authentication; the dev stack uses password auth from `.env` (never committed). No application-level accounts exist by design — the public tier is anonymous and read-only (ADR 0005). |
| (e) Transmission security | Deferred to Phase 8 deployment: TLS termination in front of the service, and moving credentials out of Temporal workflow payloads (see `docs/runbook.md`, "Security note"). Recorded here so the gap is explicit, not forgotten. |

## Identified-reports handling, concretely

- Raw report rows live only in `stg_*` staging tables; raw rejected
  lines live only in `quarantine.raw_payload`.
- The web-serving role cannot SELECT either — verified by
  `tests/test_roles_audit.py::TestRoleIsolation`.
- Logs and reports carry counts and reason codes, never raw records
  (log-hygiene rule in `docs/runbook.md`; the Phase 8 service inherits
  it).
- Nothing in this pipeline attempts re-identification, and the served
  statistics are aggregates over case counts.

## Advisory checklist (for anyone deploying a fork near real PHI)

This platform never touches PHI. If you fork it into a context that
does, this checklist is a starting point, not legal advice — engage a
qualified compliance professional.

- [ ] Determine covered-entity / business-associate status before
      writing any code.
- [ ] Execute BAAs with every hosting and tooling vendor in the path.
- [ ] Replace password auth with centrally managed identities; add MFA.
- [ ] Encrypt at rest and in transit; document key management.
- [ ] Extend the audit log to read access, not just pipeline writes.
- [ ] Define retention and disposal schedules for every table.
- [ ] Run a formal risk analysis (§164.308(a)(1)) — the administrative
      safeguards are the bulk of the work and are out of scope here.

*Prepared as part of Phase 6. No compliance claim is made anywhere in
this repository; if you find wording that reads like one, file an issue
— that's a bug.*
