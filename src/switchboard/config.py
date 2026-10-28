"""Typed environment configuration for the current gateway process."""

import os
from typing import Self

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

DEFAULT_MOCK_PROVIDER_URL = AnyHttpUrl("http://127.0.0.1:8001")


class GatewaySettings(BaseModel):
    """Validated settings needed by the gateway process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mock_provider_url: AnyHttpUrl = DEFAULT_MOCK_PROVIDER_URL
    upstream_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    upstream_read_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    upstream_write_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    upstream_pool_timeout_seconds: float = Field(default=1.0, gt=0, le=30)

    def http_timeout(self) -> httpx.Timeout:
        """Build an HTTPX timeout with every phase configured explicitly."""
        return httpx.Timeout(
            connect=self.upstream_connect_timeout_seconds,
            read=self.upstream_read_timeout_seconds,
            write=self.upstream_write_timeout_seconds,
            pool=self.upstream_pool_timeout_seconds,
        )

    @classmethod
    def from_env(cls) -> Self:
        """Load settings from environment variables with safe local defaults."""
        return cls.model_validate(
            {
                "mock_provider_url": os.getenv(
                    "SWITCHBOARD_MOCK_PROVIDER_URL", str(DEFAULT_MOCK_PROVIDER_URL)
                ),
                "upstream_connect_timeout_seconds": os.getenv(
                    "SWITCHBOARD_UPSTREAM_CONNECT_TIMEOUT_SECONDS", "2.0"
                ),
                "upstream_read_timeout_seconds": os.getenv(
                    "SWITCHBOARD_UPSTREAM_READ_TIMEOUT_SECONDS", "10.0"
                ),
                "upstream_write_timeout_seconds": os.getenv(
                    "SWITCHBOARD_UPSTREAM_WRITE_TIMEOUT_SECONDS", "2.0"
                ),
                "upstream_pool_timeout_seconds": os.getenv(
                    "SWITCHBOARD_UPSTREAM_POOL_TIMEOUT_SECONDS", "1.0"
                ),
            }
        )
