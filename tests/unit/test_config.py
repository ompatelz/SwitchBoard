"""Unit tests for typed gateway configuration."""

import pytest
from pydantic import ValidationError

from switchboard.config import GatewaySettings


def test_settings_have_safe_local_defaults() -> None:
    """A local process should target the separately started local mock service."""
    settings = GatewaySettings()

    assert str(settings.mock_provider_url) == "http://127.0.0.1:8001/"
    assert settings.http_timeout().connect == 2.0
    assert settings.http_timeout().read == 10.0
    assert settings.http_timeout().write == 2.0
    assert settings.http_timeout().pool == 1.0


def test_settings_reject_non_http_provider_url() -> None:
    """Unsupported URL schemes should fail during startup configuration."""
    with pytest.raises(ValidationError):
        GatewaySettings.model_validate({"mock_provider_url": "file:///tmp/provider"})


def test_settings_load_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Container service discovery and timeout values come from the environment."""
    monkeypatch.setenv("SWITCHBOARD_MOCK_PROVIDER_URL", "http://mock-provider:8001")
    monkeypatch.setenv("SWITCHBOARD_UPSTREAM_CONNECT_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("SWITCHBOARD_UPSTREAM_READ_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("SWITCHBOARD_UPSTREAM_WRITE_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("SWITCHBOARD_UPSTREAM_POOL_TIMEOUT_SECONDS", "1.5")

    settings = GatewaySettings.from_env()

    assert str(settings.mock_provider_url) == "http://mock-provider:8001/"
    timeout = settings.http_timeout()
    assert timeout.connect == 3.5
    assert timeout.read == 20.0
    assert timeout.write == 4.0
    assert timeout.pool == 1.5


@pytest.mark.parametrize(
    "field",
    [
        "upstream_connect_timeout_seconds",
        "upstream_read_timeout_seconds",
        "upstream_write_timeout_seconds",
        "upstream_pool_timeout_seconds",
    ],
)
def test_settings_reject_non_positive_timeouts(field: str) -> None:
    """Every timeout phase must be positive and bounded."""
    with pytest.raises(ValidationError):
        GatewaySettings.model_validate({field: 0})
