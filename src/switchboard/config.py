"""Typed environment configuration for the current gateway process."""

import json
import os
import re
from typing import Self

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, RedisDsn, model_validator

DEFAULT_MOCK_PROVIDER_URL = AnyHttpUrl("http://127.0.0.1:8001")
DEFAULT_REDIS_URL = RedisDsn("redis://127.0.0.1:6379/0")
TENANT_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class GatewaySettings(BaseModel):
    """Validated settings needed by the gateway process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mock_provider_url: AnyHttpUrl = DEFAULT_MOCK_PROVIDER_URL
    secondary_mock_provider_url: AnyHttpUrl | None = None
    provider_max_attempts: int = Field(default=2, ge=1, le=5)
    provider_deadline_seconds: float = Field(default=15.0, gt=0, le=120)
    circuit_failure_threshold: int = Field(default=3, ge=1, le=100)
    circuit_recovery_seconds: float = Field(default=10.0, gt=0, le=3600)
    tenant_key_hashes: dict[str, str] = Field(default_factory=dict)
    revoked_key_hashes: set[str] = Field(default_factory=set)
    redis_url: RedisDsn = DEFAULT_REDIS_URL
    cache_ttl_seconds: int = Field(default=300, ge=1, le=86_400)
    redis_timeout_seconds: float = Field(default=0.25, gt=0, le=5)
    rate_limit_requests: int = Field(default=120, ge=1, le=100_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    upstream_concurrency_limit: int = Field(default=32, ge=1, le=10_000)
    upstream_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    upstream_read_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    upstream_write_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    upstream_pool_timeout_seconds: float = Field(default=1.0, gt=0, le=30)
    semantic_cache_enabled: bool = False
    semantic_similarity_threshold: float = Field(default=0.98, ge=0, le=1)
    semantic_candidate_count: int = Field(default=3, ge=1, le=20)
    embedding_service_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8003")
    qdrant_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:6333")

    @model_validator(mode="after")
    def validate_credentials(self) -> Self:
        if len(set(self.tenant_key_hashes.values())) != len(self.tenant_key_hashes):
            raise ValueError("duplicate API-key digest")
        for tenant_id, digest in self.tenant_key_hashes.items():
            if not TENANT_ID_PATTERN.fullmatch(tenant_id):
                raise ValueError("invalid tenant ID")
            if not SHA256_PATTERN.fullmatch(digest):
                raise ValueError("invalid API-key digest")
        if any(not SHA256_PATTERN.fullmatch(value) for value in self.revoked_key_hashes):
            raise ValueError("invalid revoked API-key digest")
        return self

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
                "secondary_mock_provider_url": os.getenv("SWITCHBOARD_SECONDARY_MOCK_PROVIDER_URL"),
                "provider_max_attempts": os.getenv("SWITCHBOARD_PROVIDER_MAX_ATTEMPTS", "2"),
                "provider_deadline_seconds": os.getenv(
                    "SWITCHBOARD_PROVIDER_DEADLINE_SECONDS", "15"
                ),
                "circuit_failure_threshold": os.getenv(
                    "SWITCHBOARD_CIRCUIT_FAILURE_THRESHOLD", "3"
                ),
                "circuit_recovery_seconds": os.getenv("SWITCHBOARD_CIRCUIT_RECOVERY_SECONDS", "10"),
                "tenant_key_hashes": json.loads(
                    os.getenv("SWITCHBOARD_TENANT_KEY_HASHES_JSON", "{}")
                ),
                "revoked_key_hashes": json.loads(
                    os.getenv("SWITCHBOARD_REVOKED_KEY_HASHES_JSON", "[]")
                ),
                "redis_url": os.getenv("SWITCHBOARD_REDIS_URL", str(DEFAULT_REDIS_URL)),
                "cache_ttl_seconds": os.getenv("SWITCHBOARD_CACHE_TTL_SECONDS", "300"),
                "redis_timeout_seconds": os.getenv("SWITCHBOARD_REDIS_TIMEOUT_SECONDS", "0.25"),
                "rate_limit_requests": os.getenv("SWITCHBOARD_RATE_LIMIT_REQUESTS", "120"),
                "rate_limit_window_seconds": os.getenv(
                    "SWITCHBOARD_RATE_LIMIT_WINDOW_SECONDS", "60"
                ),
                "upstream_concurrency_limit": os.getenv(
                    "SWITCHBOARD_UPSTREAM_CONCURRENCY_LIMIT", "32"
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
                "semantic_cache_enabled": os.getenv("SWITCHBOARD_SEMANTIC_CACHE_ENABLED", "false"),
                "semantic_similarity_threshold": os.getenv(
                    "SWITCHBOARD_SEMANTIC_SIMILARITY_THRESHOLD", "0.98"
                ),
                "semantic_candidate_count": os.getenv("SWITCHBOARD_SEMANTIC_CANDIDATE_COUNT", "3"),
                "embedding_service_url": os.getenv(
                    "SWITCHBOARD_EMBEDDING_SERVICE_URL", "http://127.0.0.1:8003"
                ),
                "qdrant_url": os.getenv("SWITCHBOARD_QDRANT_URL", "http://127.0.0.1:6333"),
            }
        )
