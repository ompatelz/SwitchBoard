"""Integration tests for the gateway's shared upstream client."""

import httpx
from fastapi.testclient import TestClient

from switchboard.config import GatewaySettings
from switchboard.gateway import create_app


def healthy_upstream(request: httpx.Request) -> httpx.Response:
    """Return the mock-provider health contract through an in-memory transport."""
    assert request.url.path == "/healthz"
    return httpx.Response(200, json={"status": "ok", "service": "mock-provider"})


def test_lifespan_creates_and_closes_one_shared_client() -> None:
    """The pooled client exists only for the application's lifespan."""
    application = create_app(transport=httpx.MockTransport(healthy_upstream))

    with TestClient(application):
        client = application.state.http_client
        assert isinstance(client, httpx.AsyncClient)
        assert not client.is_closed

    assert client.is_closed


def test_readiness_uses_configured_shared_client() -> None:
    """Readiness succeeds through the lifespan-managed upstream client."""
    settings = GatewaySettings.model_validate(
        {
            "mock_provider_url": "http://mock-provider:8001",
            "upstream_timeout_seconds": 1.0,
        }
    )
    application = create_app(
        settings=settings,
        transport=httpx.MockTransport(healthy_upstream),
    )

    with TestClient(application) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "upstream": "mock-provider"}


def test_readiness_is_unavailable_when_upstream_fails() -> None:
    """An upstream connection failure becomes a stable readiness failure."""

    def failed_upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injected connection failure", request=request)

    application = create_app(transport=httpx.MockTransport(failed_upstream))

    with TestClient(application) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "mock_provider_unavailable"}}
