"""RxNav client behavior via MockTransport — fully offline, written first."""

from __future__ import annotations

import httpx
import pytest

from faers_signal_pipeline.normalize.rxnav import RxNavClient, RxNavError

BASE = "https://rxnav.test/REST"


def make_client(
    handler: httpx.MockTransport | None = None,
    responses: dict[str, object] | None = None,
    calls: list[str] | None = None,
    sleeps: list[float] | None = None,
    max_retries: int = 2,
) -> RxNavClient:
    """RxNavClient over a mock transport; records calls and sleeps."""

    def default_handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        name = request.url.params.get("name", "")
        payload = (responses or {}).get(name)
        if payload == "error":
            return httpx.Response(500)
        if payload is None:
            return httpx.Response(200, json={"idGroup": {"name": name}})
        return httpx.Response(200, json={"idGroup": {"name": name, "rxnormId": [payload]}})

    transport = handler or httpx.MockTransport(default_handler)
    return RxNavClient(
        http=httpx.Client(transport=transport),
        base_url=BASE,
        min_interval_seconds=0.25,
        max_retries=max_retries,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


class TestLookup:
    def test_match_returns_rxcui(self) -> None:
        client = make_client(responses={"ASPIRIN": "1191"})
        assert client.lookup_rxcui("ASPIRIN") == "1191"

    def test_no_match_returns_none(self) -> None:
        client = make_client(responses={})
        assert client.lookup_rxcui("NOT A DRUG") is None

    def test_normalized_search_parameter_sent(self) -> None:
        calls: list[str] = []
        client = make_client(responses={"ASPIRIN": "1191"}, calls=calls)
        client.lookup_rxcui("ASPIRIN")
        assert "search=2" in calls[0]

    def test_retries_transient_error_then_succeeds(self) -> None:
        attempts: list[int] = []

        def flaky(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            if len(attempts) < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"idGroup": {"rxnormId": ["10"]}})

        client = make_client(handler=httpx.MockTransport(flaky))
        assert client.lookup_rxcui("X") == "10"
        assert len(attempts) == 3

    def test_exhausted_retries_raise(self) -> None:
        client = make_client(responses={"X": "error"}, max_retries=1)
        with pytest.raises(RxNavError, match="after 2 attempts"):
            client.lookup_rxcui("X")

    def test_network_error_retries_then_raises(self) -> None:
        def dead(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        client = make_client(handler=httpx.MockTransport(dead), max_retries=1)
        with pytest.raises(RxNavError):
            client.lookup_rxcui("X")


class TestThrottle:
    def test_min_interval_enforced_between_calls(self) -> None:
        sleeps: list[float] = []
        client = make_client(responses={"A": "1", "B": "2"}, sleeps=sleeps)
        client.lookup_rxcui("A")
        client.lookup_rxcui("B")
        # Second call must wait the configured interval (monotonic clock is
        # injected as "always the same instant" via recorded sleep calls).
        assert sleeps, "expected a throttle sleep between consecutive calls"
        assert sleeps[0] > 0

    def test_backoff_sleeps_grow(self) -> None:
        sleeps: list[float] = []

        def failing(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = make_client(handler=httpx.MockTransport(failing), sleeps=sleeps, max_retries=2)
        with pytest.raises(RxNavError):
            client.lookup_rxcui("X")
        backoffs = [s for s in sleeps if s >= 0.5]
        assert len(backoffs) == 2
        assert backoffs[1] > backoffs[0]
