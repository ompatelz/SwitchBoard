"""Configuration and fail-closed API-key tests."""

import hashlib

import pytest
from pydantic import ValidationError

from switchboard.auth import ApiKeyAuthenticator, TenantIdentity
from switchboard.config import GatewaySettings


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_missing_invalid_and_revoked_keys_share_one_rejection() -> None:
    key = "random-development-key-0123456789abcdef"
    revoked = "revoked-development-key-0123456789abcdef"
    authenticator = ApiKeyAuthenticator({"alpha": digest(key)}, {digest(revoked)})
    assert authenticator.authenticate(None) is None
    assert authenticator.authenticate("Basic token") is None
    assert authenticator.authenticate("Bearer wrong") is None
    assert authenticator.authenticate(f"Bearer {revoked}") is None
    assert authenticator.authenticate(f"Bearer {key}") == TenantIdentity("alpha")


def test_empty_configuration_fails_closed() -> None:
    assert ApiKeyAuthenticator({}, set()).authenticate("Bearer any-key") is None


@pytest.mark.parametrize(
    "values",
    [
        {"tenant_key_hashes": {"INVALID TENANT": digest("key")}},
        {"tenant_key_hashes": {"alpha": "plaintext-key"}},
        {"tenant_key_hashes": {"alpha": digest("key"), "beta": digest("key")}},
        {"revoked_key_hashes": ["plaintext-key"]},
        {"cache_ttl_seconds": 0},
        {"redis_timeout_seconds": 0},
    ],
)
def test_invalid_security_settings_fail_startup(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GatewaySettings.model_validate(values)
