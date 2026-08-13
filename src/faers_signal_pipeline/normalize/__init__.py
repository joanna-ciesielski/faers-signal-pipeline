"""Drug normalization: DRUGNAME/PROD_AI -> RxNorm RXCUI via the RxNav API.

Licensing boundary (ADR 0004/0006): only the open RxNav REST API is used —
never the full RxNorm release (UMLS-licensed). Only the RXCUI identifier
and our own match metadata are persisted; no licensed vocabulary content.
No fuzzy matching in v1 (ADR 0006): every transformation is a fixed rule.
"""
