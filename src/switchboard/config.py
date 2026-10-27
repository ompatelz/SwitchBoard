"""Typed environment configuration for the current gateway process."""

import os
from typing import Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

DEFAULT_MOCK_PROVIDER_URL = AnyHttpUrl("http://127.0.0.1:8001")


class GatewaySettings(BaseModel):
    """Validated settings needed by the Phase 0C gateway."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mock_provider_url: AnyHttpUrl = DEFAULT_MOCK_PROVIDER_URL
    upstream_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    @classmethod
    def from_env(cls) -> Self:
        """Load settings from environment variables with safe local defaults."""
        return cls.model_validate(
            {
                "mock_provider_url": os.getenv(
                    "SWITCHBOARD_MOCK_PROVIDER_URL", str(DEFAULT_MOCK_PROVIDER_URL)
                ),
                "upstream_timeout_seconds": os.getenv(
                    "SWITCHBOARD_UPSTREAM_TIMEOUT_SECONDS", "2.0"
                ),
            }
        )
