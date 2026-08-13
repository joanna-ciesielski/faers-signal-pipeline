"""Parsing of FAERS quarterly ASCII extracts into typed, staged records.

Everything in this package obeys one contract: every input line either
parses cleanly or is quarantined with a machine-readable reason. Nothing is
silently dropped, repaired, or guessed at.
"""
