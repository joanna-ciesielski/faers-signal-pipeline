# Case deduplication policy

This document states exactly how `current_cases` is derived, what parts of
that derivation come from FDA's published semantics, and which parts are
our own documented policy choices. The implementation is the pure module
`src/faers_signal_pipeline/dedup/resolve.py`; every rule below has a named
test in `tests/test_dedup_resolve.py`.

## FDA basis

From the FAERS Quarterly Data Extract's own data dictionary (ASC_NTS, Last
Revised January 2025):

- A FAERS **case** (`CASEID`) is published as **versions**
  (`CASEVERSION`): "The Initial Case will be version 1; follow-ups to the
  case will have sequentially incremented version numbers."
- `PRIMARYID` is the concatenation of case id and version — one row per
  version per quarterly extract.
- Quarterly extracts are **not cumulative**; the same case may appear in
  multiple extracts as new versions (or, occasionally, the same version
  republished).
- Each quarterly archive ships a deleted-cases list
  (`Deleted/DELETE{yy}Q{q}.txt`, a headerless list of CASEIDs) naming cases
  removed from FAERS.

FDA documents *that* versions and deletions exist; it does not publish a
resolution algorithm. The rules below are therefore ours, chosen to be
deterministic, order-independent, and honest.

## Resolution rules

1. **Higher `CASEVERSION` wins.** Version numbers rank information
   recency; publication quarter does not. A late-arriving *older* version
   (v1 appearing in a quarter after v2 was already published) never
   displaces the higher version.
2. **Equal versions: latest quarter wins.** If the same version is
   republished in a later extract, the later sighting is the one
   `current_cases` points at.
3. **Deletion:** a case is removed from `current_cases` iff its latest
   deletion quarter is **greater than or equal to** its latest version
   sighting quarter.
   - *Tie rule (ours):* a version sighting and a deletion in the same
     quarter → the deletion wins. Deleting is the rarer, stronger signal.
   - *Resurrection (ours):* a version sighting in a strictly later quarter
     than the latest deletion returns the case to `current_cases`, with
     the highest version overall as current. Rationale: a post-deletion
     publication by FDA is new information about the case's existence.
   - A deletion naming a CASEID never seen in any extract is recorded and
     counted (`never_seen_deletions`), nothing else.
4. **Exact duplicate sightings** of (caseid, version, quarter) collapse to
   one row, deterministically (full sort, keep last), and are counted
   (`duplicate_sightings`) — never silently ignored.

## Materialization

`db/cases.py` rebuilds two tables from the union of all staged quarters in
one transaction (truncate-and-rebuild):

- `case_versions` — the full history: every distinct
  (caseid, version, quarter) sighting ever staged. Nothing is erased by
  deletion; deletions remove cases from *current*, not from history.
- `current_cases` — one pointer row per living case: caseid → winning
  caseversion, its source quarter, and primaryid. Payload stays in staging
  (`stg_demo` and children), joined on (quarter, primaryid).

Because the rebuild is a pure function of the staged union, **quarter load
order cannot affect the result** — the CI gate proves this end-to-end
(same quarters loaded in different orders produce identical tables) and at
the pure level (property test: any permutation of sightings/deletions
resolves identically).

## Residual duplicate risk — stated plainly

This policy deduplicates *versions of the same CASEID*. It does not, and
cannot, detect FDA's well-known **cross-case duplicates**: the same
real-world event reported through different channels under different
CASEIDs (patient + manufacturer, literature + spontaneous, multi-country).
Detecting those requires probabilistic record linkage over demographics,
drugs, and dates — explicitly out of scope for this rule-based module, and
one reason all outputs remain *signal detection, not risk quantification*.
Counts derived from `current_cases` should be read with that inflation in
mind.
