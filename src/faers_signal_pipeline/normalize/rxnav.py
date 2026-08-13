"""Polite, resilient client for the open RxNav REST API.

- Open API, no license required (the ADR 0004 boundary; the full RxNorm
  release is UMLS-licensed and never used).
- Throttled: a configurable minimum interval between requests, default
  well under RxNav's stated ceiling — this is a public-goods service.
- Retries transient failures (5xx, network errors) with growing backoff;
  a persistent failure raises ``RxNavError`` so callers can park the name
  and continue (never fail a whole run for one flaky lookup).
- The HTTP client and sleep function are injected: tests run offline with
  MockTransport and a recording sleeper.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
#: Default 0.25s -> 4 req/s, far under RxNav's documented 20 req/s ceiling.
DEFAULT_MIN_INTERVAL_SECONDS = 0.25
_BACKOFF_BASE_SECONDS = 0.5


class RxNavError(RuntimeError):
    """A lookup failed persistently (after retries)."""


@dataclass
class RxNavClient:
    """Minimal RxNav client: name -> RXCUI (normalized search) or None."""

    http: httpx.Client
    base_url: str = DEFAULT_BASE_URL
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS
    max_retries: int = 3
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    _last_request_at: float | None = field(default=None, init=False, repr=False)

    def lookup_rxcui(self, name: str) -> str | None:
        """Resolve one name to an RXCUI via /rxcui.json?search=2 (normalized).

        Returns None for a definitive no-match (a valid, cacheable answer).
        Raises RxNavError after ``max_retries + 1`` failed attempts.
        """
        url = f"{self.base_url.rstrip('/')}/rxcui.json"
        attempts = self.max_retries + 1
        last_error = ""
        for attempt in range(attempts):
            self._throttle()
            try:
                response = self.http.get(url, params={"name": name, "search": "2"}, timeout=30.0)
            except httpx.HTTPError as exc:
                last_error = str(exc)
            else:
                if response.status_code == 200:
                    payload = response.json()
                    id_group = payload.get("idGroup", {})
                    rxnorm_ids = id_group.get("rxnormId") or []
                    return str(rxnorm_ids[0]) if rxnorm_ids else None
                last_error = f"HTTP {response.status_code}"
            if attempt < attempts - 1:
                self.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
        msg = f"RxNav lookup for {name!r} failed after {attempts} attempts: {last_error}"
        raise RxNavError(msg)

    def _throttle(self) -> None:
        now = self.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            wait = self.min_interval_seconds - elapsed
            if wait > 0:
                self.sleep(wait)
        self._last_request_at = self.monotonic()
