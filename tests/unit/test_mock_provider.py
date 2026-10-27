"""Unit tests for deterministic mock-response construction."""

from switchboard.contracts import ChatCompletionRequest, ChatMessage
from switchboard.mock_provider import (
    MOCK_CREATED_TIMESTAMP,
    MockGenerationRequest,
    build_mock_chat_completion,
    build_mock_response,
)


def test_same_request_produces_same_response() -> None:
    """Determinism must not depend on object identity or invocation order."""
    first_request = MockGenerationRequest(prompt="Explain ASGI", seed=7)
    second_request = MockGenerationRequest(prompt="Explain ASGI", seed=7)

    assert build_mock_response(first_request) == build_mock_response(second_request)


def test_semantically_different_request_changes_response_id() -> None:
    """A changed validated input must produce a different identity."""
    first = build_mock_response(MockGenerationRequest(prompt="Explain ASGI", seed=7))
    second = build_mock_response(MockGenerationRequest(prompt="Explain WSGI", seed=7))

    assert first.id != second.id


def test_chat_completion_fixture_is_deterministic_and_openai_shaped() -> None:
    """Equivalent validated chat requests produce one stable completion choice."""
    request = ChatCompletionRequest(
        model="mock-v1",
        messages=[ChatMessage(role="user", content="Explain ASGI in two words")],
    )

    first = build_mock_chat_completion(request)
    second = build_mock_chat_completion(request)

    assert first == second
    assert first.id == "chatcmpl-mock-8859fb36e162c6d5e84f53b1"
    assert first.object == "chat.completion"
    assert first.created == MOCK_CREATED_TIMESTAMP
    assert first.model == "mock-v1"
    assert first.choices[0].message.role == "assistant"
    assert first.choices[0].message.content == "Deterministic mock completion 8859fb36e162c6d5"
    assert first.choices[0].finish_reason == "stop"
    assert first.usage.prompt_tokens == 5
    assert first.usage.total_tokens == (first.usage.prompt_tokens + first.usage.completion_tokens)
