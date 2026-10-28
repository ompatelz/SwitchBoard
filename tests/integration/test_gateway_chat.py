"""Integration and failure-path tests for non-streaming gateway forwarding."""

import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from switchboard.contracts import (
    AssistantMessage,
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    CompletionUsage,
)
from switchboard.gateway import create_app, get_chat_provider
from switchboard.mock_provider import create_app as create_mock_provider_app
from switchboard.provider import ChatProviderStream
from switchboard.request_ids import REQUEST_ID_HEADER, REQUEST_ID_PATTERN

VALID_REQUEST = {
    "model": "mock-v1",
    "messages": [{"role": "user", "content": "Explain ASGI"}],
}
VALID_RESPONSE = {
    "id": "chatcmpl-mock-test",
    "object": "chat.completion",
    "created": 1_700_000_000,
    "model": "mock-v1",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "An async server interface."},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6},
}


def test_valid_request_reaches_provider_and_preserves_request_id() -> None:
    """One ID is visible at the client, gateway, and provider boundaries."""
    observed_request_ids: list[str] = []

    def provider(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        observed_request_ids.append(request.headers[REQUEST_ID_HEADER])
        assert json.loads(request.content) == {**VALID_REQUEST, "stream": False}
        return httpx.Response(200, json=VALID_RESPONSE)

    application = create_app(transport=httpx.MockTransport(provider))
    with TestClient(application) as client:
        response = client.post(
            "/v1/chat/completions",
            json=VALID_REQUEST,
            headers={REQUEST_ID_HEADER: "client-request-42"},
        )

    assert response.status_code == 200
    assert response.json() == VALID_RESPONSE
    assert response.headers[REQUEST_ID_HEADER] == "client-request-42"
    assert observed_request_ids == ["client-request-42"]


def test_gateway_round_trip_uses_actual_mock_application() -> None:
    """A request crosses both ASGI applications and returns the declared contract."""
    mock_application = create_mock_provider_app()
    gateway_application = create_app(transport=httpx.ASGITransport(app=mock_application))

    with TestClient(gateway_application) as client:
        response = client.post(
            "/v1/chat/completions",
            json=VALID_REQUEST,
            headers={REQUEST_ID_HEADER: "round-trip-1"},
        )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "round-trip-1"
    assert response.json()["id"] == "chatcmpl-mock-8e8932ff074237b754ce77d5"
    assert response.json()["choices"][0]["message"]["role"] == "assistant"


def test_unsafe_request_id_is_replaced_before_forwarding() -> None:
    """An unsafe incoming correlation value is never reflected or forwarded."""
    forwarded: list[str] = []

    def provider(request: httpx.Request) -> httpx.Response:
        forwarded.append(request.headers[REQUEST_ID_HEADER])
        return httpx.Response(200, json=VALID_RESPONSE)

    with TestClient(create_app(transport=httpx.MockTransport(provider))) as client:
        response = client.post(
            "/v1/chat/completions",
            json=VALID_REQUEST,
            headers={REQUEST_ID_HEADER: "unsafe value"},
        )

    generated = response.headers[REQUEST_ID_HEADER]
    assert REQUEST_ID_PATTERN.fullmatch(generated)
    assert generated != "unsafe value"
    assert forwarded == [generated]


class FakeProvider:
    """Typed in-memory provider used to prove FastAPI dependency replacement."""

    def __init__(self) -> None:
        self.calls: list[tuple[ChatCompletionRequest, str]] = []

    async def complete(
        self, request: ChatCompletionRequest, *, request_id: str
    ) -> ChatCompletionResponse:
        self.calls.append((request, request_id))
        return ChatCompletionResponse(
            id="chatcmpl-fake",
            created=1,
            model=request.model,
            choices=[ChatCompletionChoice(message=AssistantMessage(content="fake response"))],
            usage=CompletionUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )

    async def open_stream(
        self, request: ChatCompletionRequest, *, request_id: str
    ) -> ChatProviderStream:
        """Fail loudly if a non-streaming dependency test selects the wrong path."""
        raise AssertionError("streaming path was not expected")


def test_provider_dependency_can_be_replaced_without_networking() -> None:
    """Route tests can inject a provider without changing production construction."""
    fake = FakeProvider()
    application = create_app()
    application.dependency_overrides[get_chat_provider] = lambda: fake

    with TestClient(application) as client:
        response = client.post("/v1/chat/completions", json=VALID_REQUEST)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "fake response"
    assert fake.calls[0][0].messages == [ChatMessage(role="user", content="Explain ASGI")]
    assert fake.calls[0][1] == response.headers[REQUEST_ID_HEADER]


@pytest.mark.parametrize(
    ("body", "status_code", "code"),
    [
        ('{"model":', 400, "invalid_json"),
        ('{"model":"mock-v1","messages":[]}', 422, "invalid_request"),
        (
            '{"model":"mock-v1","messages":[{"role":"user","content":"hello"}],"temperature":0.5}',
            422,
            "invalid_request",
        ),
    ],
)
def test_invalid_client_payload_uses_stable_error_envelope(
    body: str, status_code: int, code: str
) -> None:
    """Malformed JSON and contract failures remain distinct and non-sensitive."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/chat/completions",
            content=body,
            headers={"content-type": "application/json", REQUEST_ID_HEADER: "error-case"},
        )

    assert response.status_code == status_code
    assert response.headers[REQUEST_ID_HEADER] == "error-case"
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == "error-case"
    assert set(response.json()) == {"error"}


def transport_failure(
    exception_type: type[httpx.RequestError],
) -> Callable[[httpx.Request], httpx.Response]:
    """Create a transport callback that raises one HTTPX request failure."""

    def fail(request: httpx.Request) -> httpx.Response:
        raise exception_type("injected secret internal failure", request=request)

    return fail


@pytest.mark.parametrize(
    ("exception_type", "status_code", "code"),
    [
        (httpx.ConnectError, 502, "provider_connection_error"),
        (httpx.ConnectTimeout, 504, "provider_timeout"),
        (httpx.ReadTimeout, 504, "provider_timeout"),
        (httpx.WriteTimeout, 504, "provider_timeout"),
        (httpx.PoolTimeout, 504, "provider_timeout"),
    ],
)
def test_transport_failures_are_bounded_and_translated(
    exception_type: type[httpx.RequestError], status_code: int, code: str
) -> None:
    """Connection and every timeout category map to documented gateway errors."""
    application = create_app(transport=httpx.MockTransport(transport_failure(exception_type)))
    with TestClient(application) as client:
        response = client.post("/v1/chat/completions", json=VALID_REQUEST)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.text


@pytest.mark.parametrize(
    ("provider_status", "gateway_status", "code"),
    [
        (400, 502, "provider_rejected_request"),
        (429, 429, "provider_rate_limited"),
        (500, 503, "provider_unavailable"),
    ],
)
def test_provider_statuses_remain_distinguishable(
    provider_status: int, gateway_status: int, code: str
) -> None:
    """Provider rejection, throttling, and server failure are not collapsed together."""

    def provider(_: httpx.Request) -> httpx.Response:
        return httpx.Response(provider_status, text="secret provider details")

    with TestClient(create_app(transport=httpx.MockTransport(provider))) as client:
        response = client.post("/v1/chat/completions", json=VALID_REQUEST)

    assert response.status_code == gateway_status
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "provider_response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(302, headers={"location": "https://internal.example"}),
    ],
)
def test_invalid_provider_response_fails_safely(provider_response: httpx.Response) -> None:
    """Invalid JSON, schemas, and unexpected statuses never reach the client unchanged."""

    def provider(_: httpx.Request) -> httpx.Response:
        return provider_response

    with TestClient(create_app(transport=httpx.MockTransport(provider))) as client:
        response = client.post("/v1/chat/completions", json=VALID_REQUEST)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_provider_response"
    assert "internal.example" not in response.text


class TrackingStream(httpx.AsyncByteStream):
    """Response body that records whether HTTPX returned its connection resource."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.content

    async def aclose(self) -> None:
        self.closed = True


def test_provider_response_body_is_closed_after_validation() -> None:
    """The adapter releases a successful response after buffering and validation."""
    stream = TrackingStream(json.dumps(VALID_RESPONSE).encode())

    def provider(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    with TestClient(create_app(transport=httpx.MockTransport(provider))) as client:
        response = client.post("/v1/chat/completions", json=VALID_REQUEST)

    assert response.status_code == 200
    assert stream.closed
