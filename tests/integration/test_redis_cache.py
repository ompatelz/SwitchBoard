"""Opt-in verification against a real Redis server."""

import asyncio
import os
import secrets

import pytest
import redis.asyncio as redis

from switchboard.auth import TenantIdentity
from switchboard.contracts import ChatCompletionRequest, ChatMessage
from switchboard.exact_cache import ExactCache, exact_cache_key
from switchboard.mock_provider import build_mock_chat_completion

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
