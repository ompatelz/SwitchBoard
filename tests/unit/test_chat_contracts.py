"""Unit tests for the Phase 1A Chat Completions boundary models."""

import pytest
from pydantic import ValidationError

from switchboard.contracts import ChatCompletionRequest


def test_supported_request_applies_non_streaming_default() -> None:
    """The declared request subset validates and defaults stream to false."""
    request = ChatCompletionRequest.model_validate(
        {
            "model": "mock-v1",
            "messages": [
                {"role": "system", "content": "Answer concisely."},
                {"role": "user", "content": "Explain ASGI."},
                {"role": "assistant", "content": "ASGI is an async interface."},
            ],
        }
    )

    assert request.model == "mock-v1"
    assert request.stream is False
    assert [message.role for message in request.messages] == ["system", "user", "assistant"]


def test_streaming_request_is_explicitly_supported() -> None:
    """A strict JSON boolean enables the Phase 1C streaming path."""
    request = ChatCompletionRequest.model_validate(
        {
            "model": "mock-v1",
            "messages": [{"role": "user", "content": "stream this"}],
            "stream": True,
        }
    )

    assert request.stream is True


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({"model": "mock-v1", "messages": []}, "too_short"),
        (
            {"model": "mock-v1", "messages": [{"role": "tool", "content": "result"}]},
            "literal_error",
        ),
        (
            {"model": "mock-v1", "messages": [{"role": "user", "content": "   "}]},
            "value_error",
        ),
        (
            {"model": "mock-v1", "messages": [{"role": "user", "content": 42}]},
            "string_type",
        ),
        (
            {
                "model": "mock-v1",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 0.2,
            },
            "extra_forbidden",
        ),
        (
            {
                "model": "mock-v1",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": 1,
            },
            "bool_type",
        ),
        (
            {
                "model": "m" * 129,
                "messages": [{"role": "user", "content": "hello"}],
            },
            "string_too_long",
        ),
        (
            {
                "model": "mock-v1",
                "messages": [{"role": "user", "content": "x" * 32_769}],
            },
            "string_too_long",
        ),
        (
            {
                "model": "mock-v1",
                "messages": [{"role": "user", "content": "x"}] * 65,
            },
            "too_long",
        ),
    ],
)
def test_invalid_or_unsupported_request_is_rejected(
    payload: dict[str, object], error_type: str
) -> None:
    """Invalid types, limits, roles, streaming, and unknown fields fail predictably."""
    with pytest.raises(ValidationError) as raised:
        ChatCompletionRequest.model_validate(payload)

    assert raised.value.errors()[0]["type"] == error_type
