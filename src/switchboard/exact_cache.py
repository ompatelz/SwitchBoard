"""Tenant-scoped exact cache for successful buffered Chat Completions."""

import hashlib
import json
from collections.abc import Awaitable
from typing import Protocol

from pydantic import ValidationError
from redis.exceptions import RedisError

from switchboard.auth import TenantIdentity
from switchboard.contracts import ChatCompletionRequest, ChatCompletionResponse

CACHE_SCHEMA_VERSION = 1


class AsyncCacheClient(Protocol):
    """Small awaited Redis surface used by the cache and its test fakes."""

    def get(self, name: str) -> Awaitable[bytes | str | None]: ...

    def set(self, name: str, value: bytes, *, ex: int) -> Awaitable[object]: ...

    def ping(self) -> Awaitable[object]: ...

    def aclose(self) -> Awaitable[None]: ...


def exact_cache_key(
    tenant: TenantIdentity, request: ChatCompletionRequest, *, provider_policy: str
) -> str:
    """Hash all current response-affecting inputs without exposing prompt text."""
    canonical = json.dumps(
        {
            "schema": CACHE_SCHEMA_VERSION,
            "tenant": tenant.tenant_id,
            "provider_policy": provider_policy,
            "request": request.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"switchboard:exact:v{CACHE_SCHEMA_VERSION}:{hashlib.sha256(canonical).hexdigest()}"


class ExactCache:
    """Fail-open cache; Redis errors never replace an allowed provider call."""

    def __init__(self, client: AsyncCacheClient, *, ttl_seconds: int, provider_policy: str) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.provider_policy = provider_policy

    async def lookup(
        self, tenant: TenantIdentity, request: ChatCompletionRequest
    ) -> ChatCompletionResponse | None:
        key = exact_cache_key(tenant, request, provider_policy=self.provider_policy)
        try:
            raw = await self.client.get(key)
        except (RedisError, TimeoutError, OSError):
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            if payload["schema"] != CACHE_SCHEMA_VERSION:
                return None
            response = ChatCompletionResponse.model_validate(payload["response"])
            return response if response.model == request.model else None
        except (ValueError, TypeError, KeyError, ValidationError):
            return None

    async def store(
        self,
        tenant: TenantIdentity,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
    ) -> None:
        key = exact_cache_key(tenant, request, provider_policy=self.provider_policy)
        value = json.dumps(
            {"schema": CACHE_SCHEMA_VERSION, "response": response.model_dump(mode="json")},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            await self.client.set(key, value, ex=self.ttl_seconds)
        except (RedisError, TimeoutError, OSError):
            return
