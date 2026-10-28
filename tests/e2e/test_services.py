"""Opt-in smoke test for locally running or Compose-managed services."""

import json
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
    generation_payload = {"prompt": "Phase 0C smoke test", "model": "mock-v1", "seed": 7}
    chat_payload = {
        "model": "mock-v1",
        "messages": [{"role": "user", "content": "Phase 1C smoke test"}],
    }

    with httpx.Client(timeout=5.0) as client:
        gateway_health = client.get(f"{gateway_url}/healthz")
        gateway_ready = client.get(f"{gateway_url}/readyz")
        mock_health = client.get(f"{mock_url}/healthz")
        first = client.post(f"{mock_url}/generate", json=generation_payload)
        second = client.post(f"{mock_url}/generate", json=generation_payload)
        first_chat = client.post(
            f"{gateway_url}/v1/chat/completions",
            json=chat_payload,
            headers={"x-request-id": "compose-smoke-1"},
        )
        second_chat = client.post(f"{gateway_url}/v1/chat/completions", json=chat_payload)
        streaming_chat = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={**chat_payload, "stream": True},
        )

    for response in (
        gateway_health,
        gateway_ready,
        mock_health,
        first,
        second,
        first_chat,
        second_chat,
        streaming_chat,
    ):
        assert response.status_code == 200

    assert gateway_health.json() == {"status": "ok", "service": "gateway"}
    assert gateway_ready.json() == {"status": "ready", "upstream": "mock-provider"}
    assert mock_health.json() == {"status": "ok", "service": "mock-provider"}
    assert first.json() == second.json()
    assert first_chat.json() == second_chat.json()
    assert first_chat.headers["x-request-id"] == "compose-smoke-1"
    assert first_chat.json()["object"] == "chat.completion"
    assert streaming_chat.headers["content-type"].startswith("text/event-stream")
    stream_events = [
        line[6:] for line in streaming_chat.text.splitlines() if line.startswith("data: ")
    ]
    assert stream_events[-1] == "[DONE]"
    chunks = [json.loads(event) for event in stream_events[:-1]]
    assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)
    assert all("usage" not in chunk for chunk in chunks)
