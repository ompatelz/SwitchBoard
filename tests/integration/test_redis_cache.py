"""Opt-in verification against a real Redis server."""

import asyncio
import hashlib
import os
import secrets

import pytest
import redis.asyncio as redis

from switchboard.auth import TenantIdentity
from switchboard.contracts import ChatCompletionRequest, ChatMessage
from switchboard.exact_cache import ExactCache, exact_cache_key
from switchboard.mock_provider import build_mock_chat_completion
from switchboard.rate_limit import FixedWindowRateLimiter

pytestmark = [
    pytest.mark.redis,
    pytest.mark.skipif(
        not os.getenv("SWITCHBOARD_REDIS_INTEGRATION_URL"),
        reason="set SWITCHBOARD_REDIS_INTEGRATION_URL for a running Redis service",
    ),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_redis_set_ttl_hit_and_expiry() -> None:
    url = os.environ["SWITCHBOARD_REDIS_INTEGRATION_URL"]
    client = redis.Redis.from_url(url, decode_responses=False, socket_timeout=1)
    policy = f"integration-{secrets.token_hex(8)}"
    cache = ExactCache(client, ttl_seconds=1, provider_policy=policy)
    tenant = TenantIdentity("integration")
    request = ChatCompletionRequest(
        model="mock-v1", messages=[ChatMessage(role="user", content="redis integration")]
    )
    response = build_mock_chat_completion(request)
    key = exact_cache_key(tenant, request, provider_policy=policy)
    try:
        assert await client.ping()
        assert await cache.lookup(tenant, request) is None
        await cache.store(tenant, request, response)
        assert await cache.lookup(tenant, request) == response
        ttl = await client.ttl(key)
        assert ttl in {0, 1}
        await asyncio.sleep(1.05)
        assert await cache.lookup(tenant, request) is None
    finally:
        await client.delete(key)
        await client.aclose()


@pytest.mark.anyio
async def test_real_redis_rate_decisions_are_atomic_and_tenant_isolated() -> None:
    url = os.environ["SWITCHBOARD_REDIS_INTEGRATION_URL"]
    client = redis.Redis.from_url(url, decode_responses=False, socket_timeout=1)
    limiter = FixedWindowRateLimiter(client, limit=5, window_seconds=10)
    tenant_a = TenantIdentity(f"integration-a-{secrets.token_hex(8)}")
    tenant_b = TenantIdentity(f"integration-b-{secrets.token_hex(8)}")
    keys = [
        f"switchboard:rate:v1:{hashlib.sha256(tenant.tenant_id.encode()).hexdigest()}"
        for tenant in (tenant_a, tenant_b)
    ]
    try:
        decisions = await asyncio.gather(*(limiter.decide(tenant_a) for _ in range(30)))
        assert sum(decision.allowed for decision in decisions) == 5
        assert all(decision.reset_seconds > 0 for decision in decisions)
        other = await asyncio.gather(*(limiter.decide(tenant_b) for _ in range(5)))
        assert all(decision.allowed for decision in other)
    finally:
        await client.delete(*keys)
        await client.aclose()
