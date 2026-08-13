"""Case versioning & deduplication — the centerpiece of this pipeline.

FAERS publishes cases as versions (CASEID x CASEVERSION), revised across
quarters, occasionally deleted, occasionally out of order. Everything in
this package is pure (frames in, frames out, no I/O) so the rules are
exhaustively testable in isolation; ``db/cases.py`` applies them to staged
data. The full policy, its FDA basis, and its explicitly-ours choices live
in ``docs/dedup-policy.md``.
"""
