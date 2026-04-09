"""Integration smoke test proving the retry transport is actually wired in."""

import httpx
from httpx_retries import Retry, RetryTransport


def test_retry_transport_retries_on_503_then_succeeds():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    retry = Retry(
        total=5,
        backoff_factor=0.0,
        max_backoff_wait=1.0,
        status_forcelist=[503],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    transport = RetryTransport(transport=httpx.MockTransport(handler), retry=retry)
    with httpx.Client(transport=transport) as client:
        response = client.get("https://example.test/x")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert attempts["count"] == 3, "expected 2 failures then 1 success"


def test_retry_transport_gives_up_after_total_attempts():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(503, headers={"Retry-After": "0"})

    retry = Retry(
        total=3,
        backoff_factor=0.0,
        max_backoff_wait=1.0,
        status_forcelist=[503],
        allowed_methods=["GET"],
    )
    transport = RetryTransport(transport=httpx.MockTransport(handler), retry=retry)
    with httpx.Client(transport=transport) as client:
        response = client.get("https://example.test/x")

    assert response.status_code == 503
    assert attempts["count"] == 4, "expected original attempt + 3 retries"


def test_retry_transport_does_not_retry_404():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(404)

    retry = Retry(
        total=5,
        backoff_factor=0.0,
        status_forcelist=[503, 500, 502],
        allowed_methods=["GET"],
    )
    transport = RetryTransport(transport=httpx.MockTransport(handler), retry=retry)
    with httpx.Client(transport=transport) as client:
        response = client.get("https://example.test/missing")

    assert response.status_code == 404
    assert attempts["count"] == 1, "404 should not be retried"
