"""FAERS signal pipeline: public pharmacovigilance data platform.

ETL over FDA FAERS quarterly extracts -> PostgreSQL 16 + pgvector,
PRR/ROR disproportionality statistics behind a CI quality gate.

FAERS data is spontaneous reporting: no denominators, duplicate reports,
stimulated reporting. Everything this package computes is signal detection,
not risk quantification, and is not medical advice.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
