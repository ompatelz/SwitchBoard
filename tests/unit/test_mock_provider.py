"""Unit tests for deterministic mock-response construction."""

from switchboard.mock_provider import MockGenerationRequest, build_mock_response


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
