"""Opt-in smoke test for locally running or Compose-managed services."""

import os

import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("SWITCHBOARD_E2E") != "1",
        reason="set SWITCHBOARD_E2E=1 after starting both services",
    ),
]


def test_running_services_are_healthy_and_deterministic() -> None:
    """Verify the real gateway-to-provider boundary and mock endpoint."""
    gateway_url = os.getenv("SWITCHBOARD_E2E_GATEWAY_URL", "http://127.0.0.1:8000")
    mock_url = os.getenv("SWITCHBOARD_E2E_MOCK_URL", "http://127.0.0.1:8001")
    payload = {"prompt": "Phase 0C smoke test", "model": "mock-v1", "seed": 7}

    with httpx.Client(timeout=5.0) as client:
        gateway_health = client.get(f"{gateway_url}/healthz")
        gateway_ready = client.get(f"{gateway_url}/readyz")
        mock_health = client.get(f"{mock_url}/healthz")
        first = client.post(f"{mock_url}/generate", json=payload)
        second = client.post(f"{mock_url}/generate", json=payload)

    assert gateway_health.json() == {"status": "ok", "service": "gateway"}
    assert gateway_ready.json() == {"status": "ready", "upstream": "mock-provider"}
    assert mock_health.json() == {"status": "ok", "service": "mock-provider"}
    assert first.status_code == 200
    assert first.json() == second.json()
