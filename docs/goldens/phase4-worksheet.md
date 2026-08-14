# Phase 4 golden-value worksheet

> **Status: COMPLETED 2026-08-13 under an explicit maintainer waiver of
> standing rule 6.** Values were computed by the assisting engineer via
> manual step-by-step arithmetic, independently verified against scipy and
> statsmodels, then compared to the pipeline (three-way agreement). Filled
> values and worked arithmetic: tests/goldens/phase4_goldens.json and
> tests/test_signal_stats.py. This worksheet is retained as the record of
> the method.

Per standing rule 6: the statistics below are computed **by hand by the
maintainer**; the pipeline's implementation is validated against them —
never the other way around. Fill the blanks, keep your worked arithmetic
(it goes into the test comments), and transfer the values into
`tests/goldens/phase4_goldens.json`.

## The corpus (count it yourself if you wish)

20 cases. Drugs in CAPS, reactions after the colon.

| Case | Drugs | Reactions |
|---|---|---|
| 1001 | ALPHADRUG | Nausea |
| 1002 | ALPHADRUG | Nausea |
| 1003 | ALPHADRUG | Nausea, Headache |
| 1004 | ALPHADRUG | Nausea, Rash |
| 1005 | ALPHADRUG | Nausea |
| 1006 | ALPHADRUG | Headache |
| 1007 | ALPHADRUG | Dizziness |
| 1008 | BETADRUG | Nausea |
| 1009 | BETADRUG | Nausea |
| 1010 | BETADRUG | Nausea |
| 1011 | BETADRUG | Headache |
| 1012 | BETADRUG | Rash |
| 1013 | GAMMADRUG | Rash |
| 1014 | GAMMADRUG | Rash |
| 1015 | GAMMADRUG | Rash |
| 1016 | GAMMADRUG | Dizziness |
| 1017 | ALPHADRUG, BETADRUG | Nausea, Dizziness |
| 1018 | GAMMADRUG | Headache |
| 1019 | UNMAPPABLE TONIC | Nausea |
| 1020 | ALPHADRUG (listed twice) | Nausea (listed twice) |

Counting policy: one count per case per (drug, reaction) pair; case 1020's
duplicates count once; case 1019's drug is unmappable, so it contributes to
reaction margins only. N = 20.

## The formulas (cited)

- PRR = (a/(a+b)) / (c/(c+d))   — Evans et al. 2001
- 95% CI: exp( ln PRR ± 1.96 × √(1/a − 1/(a+b) + 1/c − 1/(c+d)) )
- ROR = (a·d) / (b·c)           — van Puijenbroek et al. 2002
- 95% CI: exp( ln ROR ± 1.96 × √(1/a + 1/b + 1/c + 1/d) )
- χ² = N·(a·d − b·c)² / ((a+b)(c+d)(a+c)(b+d)) — Pearson, 1 df, **no**
  continuity correction. N = a+b+c+d.

Round to 3 decimal places. A plain calculator is fine; keep your steps.

## The worksheet

### Pair 1 — ALPHADRUG × Nausea: a=7, b=2, c=4, d=7 (N=20)

| Statistic | Your value |
|---|---|
| PRR | ______ |
| PRR 95% CI low | ______ |
| PRR 95% CI high | ______ |
| ROR | ______ |
| ROR 95% CI low | ______ |
| ROR 95% CI high | ______ |
| χ² | ______ |

### Pair 2 — BETADRUG × Nausea: a=4, b=2, c=7, d=7 (N=20)

| Statistic | Your value |
|---|---|
| PRR | ______ |
| PRR 95% CI low | ______ |
| PRR 95% CI high | ______ |
| ROR | ______ |
| ROR 95% CI low | ______ |
| ROR 95% CI high | ______ |
| χ² | ______ |

### Pair 3 — GAMMADRUG × Rash: a=3, b=2, c=2, d=13 (N=20)

| Statistic | Your value |
|---|---|
| PRR | ______ |
| PRR 95% CI low | ______ |
| PRR 95% CI high | ______ |
| ROR | ______ |
| ROR 95% CI low | ______ |
| ROR 95% CI high | ______ |
| χ² | ______ |

When done: paste the 21 values back (or fill the JSON directly). They
become the golden tests, your arithmetic goes into the comments, and the
mutation spot-check (break a formula ⇒ a golden fails) activates.
