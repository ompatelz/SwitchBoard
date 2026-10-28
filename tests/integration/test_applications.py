"""In-process HTTP integration tests for both ASGI applications."""

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from switchboard.gateway import create_app as create_gateway_app
from switchboard.mock_provider import create_app as create_mock_provider_app


@pytest.mark.parametrize(
    ("app_factory", "service"),
    [
        (create_gateway_app, "gateway"),
        (create_mock_provider_app, "mock-provider"),
    ],
)
def test_health_endpoint(app_factory: Callable[[], FastAPI], service: str) -> None:
    """Each application exposes its own stable health contract."""
    with TestClient(app_factory()) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": service}


def test_mock_endpoint_is_deterministic_across_requests() -> None:
    """Equivalent HTTP requests return equivalent JSON data."""
    payload = {"prompt": "Explain ASGI", "model": "mock-v1", "seed": 7}

    with TestClient(create_mock_provider_app()) as client:
        first = client.post("/generate", json=payload)
        second = client.post("/generate", json=payload)

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["model"] == "mock-v1"


def test_mock_chat_completions_endpoint_is_deterministic() -> None:
    """The mock provider serves the documented non-streaming response contract."""
    payload = {
        "model": "mock-v1",
        "messages": [{"role": "user", "content": "Explain ASGI"}],
    }

    with TestClient(create_mock_provider_app()) as client:
        first = client.post("/v1/chat/completions", json=payload)
        second = client.post("/v1/chat/completions", json={**payload, "stream": False})

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["object"] == "chat.completion"
    assert first.json()["choices"][0]["message"]["role"] == "assistant"


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({"model": "mock-v1", "messages": []}, "too_short"),
        (
            {"model": "mock-v1", "messages": [{"role": "developer", "content": "x"}]},
            "literal_error",
        ),
        (
            {
                "model": "mock-v1",
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 10,
            },
            "extra_forbidden",
        ),
    ],
)
def test_mock_chat_completions_rejects_invalid_requests(
    payload: dict[str, object], error_type: str
) -> None:
    """HTTP validation exposes the same strict boundary as direct model validation."""
    with TestClient(create_mock_provider_app()) as client:
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == error_type


def test_mock_chat_completions_streams_deterministic_sse() -> None:
    """The mock emits fragmented frames that reassemble into chunks and [DONE]."""
    payload = {
        "model": "mock-v1",
        "messages": [{"role": "user", "content": "Explain ASGI"}],
        "stream": True,
    }

    with TestClient(create_mock_provider_app()) as client:
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    assert len(events) == 6


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({"prompt": "   "}, "string_too_short"),
        ({"prompt": "valid", "unexpected": True}, "extra_forbidden"),
        ({"prompt": "valid", "model": "not-supported"}, "literal_error"),
        ({"prompt": "valid", "seed": -1}, "greater_than_equal"),
    ],
)
def test_mock_endpoint_rejects_invalid_input(payload: dict[str, object], error_type: str) -> None:
    """Invalid inputs receive FastAPI's stable validation-error response."""
    with TestClient(create_mock_provider_app()) as client:
        response = client.post("/generate", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == error_type
