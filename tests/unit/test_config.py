"""Unit tests for typed gateway configuration."""

import pytest
from pydantic import ValidationError

from switchboard.config import GatewaySettings


def test_settings_have_safe_local_defaults() -> None:
    """A local process should target the separately started local mock service."""
    settings = GatewaySettings()

    assert str(settings.mock_provider_url) == "http://127.0.0.1:8001/"
    assert settings.upstream_timeout_seconds == 2.0


def test_settings_reject_non_http_provider_url() -> None:
    """Unsupported URL schemes should fail during startup configuration."""
    with pytest.raises(ValidationError):
        GatewaySettings.model_validate({"mock_provider_url": "file:///tmp/provider"})


def test_settings_load_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Container service discovery and timeout values come from the environment."""
    monkeypatch.setenv("SWITCHBOARD_MOCK_PROVIDER_URL", "http://mock-provider:8001")
    monkeypatch.setenv("SWITCHBOARD_UPSTREAM_TIMEOUT_SECONDS", "3.5")

    settings = GatewaySettings.from_env()

    assert str(settings.mock_provider_url) == "http://mock-provider:8001/"
    assert settings.upstream_timeout_seconds == 3.5
