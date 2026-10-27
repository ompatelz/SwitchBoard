"""Unit tests for safe request-ID acceptance and generation."""

from switchboard.request_ids import REQUEST_ID_PATTERN, resolve_request_id


def test_safe_incoming_request_id_is_preserved() -> None:
    """A bounded log-safe identifier may be correlated across services."""
    assert resolve_request_id("client.request-42_A") == "client.request-42_A"


def test_absent_or_unsafe_request_id_is_replaced() -> None:
    """Control characters, spaces, and oversized values never cross the boundary."""
    for candidate in (None, "contains spaces", "line\nbreak", "x" * 65):
        resolved = resolve_request_id(candidate)

        assert REQUEST_ID_PATTERN.fullmatch(resolved)
        assert resolved != candidate
