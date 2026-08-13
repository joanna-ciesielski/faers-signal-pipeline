# ADR 0005 — Free public tier carries no advertising

- Status: accepted
- Date: 2026-08-12
- Review: none scheduled. This decision is recorded as final; re-opening it
  requires new written evidence and a superseding ADR.

## Context

The pipeline will be published as a free, read-only public web explorer
(Phase 8). Free public websites conventionally reach for programmatic
advertising as a default monetization layer. This ADR records the decision
not to, and why, so the question does not get re-litigated casually.

The service's subject matter is adverse drug events: pages a worried patient
may reach while searching for their own medication. This is
"Your Money or Your Life" content in every meaningful sense, served from
spontaneous-report data that is easy to misread as risk quantification.

## Decision

The public tier is read-only, requires no accounts, and carries
**no advertising of any kind** — no programmatic display ads, no ad
networks, no affiliate placements, no sponsored content within results.

If consumer-side goodwill revenue is ever wanted, the only acceptable forms
are: a donation link, or a single vetted non-programmatic sponsor line —
nothing else, and neither may appear on or beside results surfaces.

## Rationale (on record)

1. **Ethics and credibility.** Programmatic ad networks against drug-safety
   content would serve drug, supplement, and litigation ads next to
   adverse-event data — including to worried patients reading about their
   own medication. Monetizing that attention while presenting safety
   signals is a credibility failure the project could not recover from.
2. **The economics are trivial.** At realistic niche traffic, programmatic
   advertising yields tens of dollars per month at best — while actively
   cheapening the asset's primary value as a professional credential. To
   the professional evaluators this platform exists to persuade, ads on the
   flagship read as amateur.
3. **Duty of care to lay visitors.** Serving the public raises the duty of
   care: spontaneous-report data without denominators is easy to misread.
   The correct response is prominent plain-language disclaimers and careful
   presentation — not monetization of that audience.

## Consequences

- Revenue, if any, comes from the single B2B experiment (watchlist alerts,
  Phase 9) — never from the free tier's audience.
- Every results surface carries the plain-language disclaimer block
  (spontaneous reports; no denominators; signal detection, not risk
  quantification; not medical advice). Presentation choices avoid implying
  risk ranking (e.g. no severity color-coding).
- The free clean-data API remains free (rate-limited); it is a funnel that
  demonstrates pipeline quality, not a product.
- Positioning everywhere: research and monitoring tool — never clinical
  decision support, never a system of record.
