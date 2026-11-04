"""Atomic Redis-backed per-tenant request windows."""

import hashlib
from dataclasses import dataclass

from redis.exceptions import RedisError

from switchboard.auth import TenantIdentity
from switchboard.exact_cache import AsyncCacheClient

WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    remaining: int
    reset_seconds: int


class RateLimitUnavailable(Exception):
    """Redis could not make a trustworthy enforcement decision."""


class FixedWindowRateLimiter:
    """One atomic counter window anchored to each tenant's first request."""

    def __init__(self, client: AsyncCacheClient, *, limit: int, window_seconds: int) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("invalid rate policy")
        self.client = client
        self.limit = limit
        self.window_seconds = window_seconds

    async def decide(self, tenant: TenantIdentity) -> RateDecision:
        tenant_digest = hashlib.sha256(tenant.tenant_id.encode()).hexdigest()
        key = f"switchboard:rate:v1:{tenant_digest}"
        try:
            raw = await self.client.eval(WINDOW_SCRIPT, 1, key, self.window_seconds)
            if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                raise RateLimitUnavailable
            count, ttl = int(raw[0]), int(raw[1])
            if count < 1 or ttl < 0:
                raise RateLimitUnavailable
        except (RedisError, TimeoutError, OSError, ValueError, TypeError, IndexError) as exc:
            raise RateLimitUnavailable from exc
        return RateDecision(
            allowed=count <= self.limit,
            remaining=max(0, self.limit - count),
            reset_seconds=ttl,
        )
