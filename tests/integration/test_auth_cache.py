"""Tenant authentication and exact-cache request-path tests."""

import hashlib
import json

import httpx
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from switchboard.auth import TenantIdentity
from switchboard.config import GatewaySettings
from switchboard.contracts import ChatCompletionRequest
from switchboard.exact_cache import exact_cache_key
from switchboard.gateway import create_app
from switchboard.mock_provider import build_mock_chat_completion, build_mock_stream_chunks

KEY_A = "tenant-a-test-key-0123456789abcdef0123456789"
KEY_B = "tenant-b-test-key-0123456789abcdef0123456789"
REVOKED_KEY = "revoked-test-key-0123456789abcdef0123456789"
REQUEST = {"model": "mock-v1", "messages": [{"role": "user", "content": "private prompt"}]}


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def settings(**overrides: object) -> GatewaySettings:
    return GatewaySettings.model_validate(
        {
            "tenant_key_hashes": {"tenant-a": digest(KEY_A), "tenant-b": digest(KEY_B)},
            "revoked_key_hashes": [digest(REVOKED_KEY)],
            "cache_ttl_seconds": 5,
            **overrides,
        }
    )


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


class MemoryRedis:
    """Awaited fake with controllable TTL and failure state."""

    def __init__(self) -> None:
        self.now = 0.0
        self.values: dict[str, tuple[bytes, float]] = {}
        self.fail = False
        self.closed = False
        self.get_count = 0
        self.set_count = 0
        self.rate_fail = False
        self.windows: dict[str, tuple[int, float]] = {}

    async def get(self, name: str) -> bytes | None:
        self.get_count += 1
        if self.fail:
            raise RedisConnectionError("private redis URL")
        entry = self.values.get(name)
        return entry[0] if entry is not None and self.now < entry[1] else None

    async def set(self, name: str, value: bytes, *, ex: int) -> bool:
        self.set_count += 1
        if self.fail:
            raise RedisConnectionError("private redis URL")
        self.values[name] = (value, self.now + ex)
        return True

    async def ping(self) -> bool:
        if self.fail:
            raise RedisConnectionError("private redis URL")
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        if self.rate_fail:
            raise RedisConnectionError("private redis URL")
        key = str(keys_and_args[0])
        duration = int(str(keys_and_args[1]))
        count, expiry = self.windows.get(key, (0, self.now + duration))
        if self.now >= expiry:
            count, expiry = 0, self.now + duration
        count += 1
        self.windows[key] = (count, expiry)
        return [count, int(expiry - self.now)]

    async def aclose(self) -> None:
        self.closed = True


class MockUpstream:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, upstream: httpx.Request) -> httpx.Response:
        self.calls += 1
        request = ChatCompletionRequest.model_validate_json(upstream.content)
        if request.stream:
            chunks = build_mock_stream_chunks(request)
            body = (
                b"".join(
                    f"data: {chunk.model_dump_json(exclude_none=True)}\n\n".encode()
                    for chunk in chunks
                )
                + b"data: [DONE]\n\n"
            )
            return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=build_mock_chat_completion(request).model_dump(mode="json"))


def test_rejected_keys_never_reach_provider_or_cache() -> None:
    redis = MemoryRedis()
    upstream = MockUpstream()
    with TestClient(
        create_app(settings(), transport=httpx.MockTransport(upstream), redis_client=redis)
    ) as client:
        responses = [
            client.post("/v1/chat/completions", json=REQUEST),
            client.post("/v1/chat/completions", json=REQUEST, headers=auth("wrong-key")),
            client.post("/v1/chat/completions", json=REQUEST, headers=auth(REVOKED_KEY)),
        ]
    assert [response.status_code for response in responses] == [401, 401, 401]
    assert {response.json()["error"]["code"] for response in responses} == {"invalid_api_key"}
    assert all(response.headers["www-authenticate"] == "Bearer" for response in responses)
    assert upstream.calls == redis.get_count == 0
    assert redis.closed


def test_tenant_isolation_exact_hit_and_input_change() -> None:
    redis = MemoryRedis()
    upstream = MockUpstream()
    with TestClient(
        create_app(settings(), transport=httpx.MockTransport(upstream), redis_client=redis)
    ) as client:
        first = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        second = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        other = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_B))
        changed = client.post(
            "/v1/chat/completions",
            json={**REQUEST, "messages": [{"role": "user", "content": "different"}]},
            headers=auth(KEY_A),
        )
    assert all(response.status_code == 200 for response in (first, second, other, changed))
    assert first.json() == second.json() == other.json()
    assert changed.json() != first.json()
    assert upstream.calls == 3
    assert len(redis.values) == 3


def test_ttl_expiry_and_corrupt_entry_return_to_provider() -> None:
    redis = MemoryRedis()
    upstream = MockUpstream()
    with TestClient(
        create_app(settings(), transport=httpx.MockTransport(upstream), redis_client=redis)
    ) as client:
        client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        redis.now = 5
        client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        key = next(iter(redis.values))
        redis.values[key] = (b"{bad-json", 100)
        client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        redis.values[key] = (b'{"schema":999,"response":{}}', 100)
        client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        redis.values[key] = (b'{"schema":1,"response":{"invalid":true}}', 100)
        client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        wrong_model = build_mock_chat_completion(ChatCompletionRequest.model_validate(REQUEST))
        redis.values[key] = (
            json.dumps(
                {
                    "schema": 1,
                    "response": wrong_model.model_copy(update={"model": "other"}).model_dump(),
                }
            ).encode(),
            100,
        )
        client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
    assert upstream.calls == 6
    assert redis.set_count == 6


def test_redis_outage_fails_open_and_health_is_separate() -> None:
    redis = MemoryRedis()
    redis.fail = True
    upstream = MockUpstream()
    with TestClient(
        create_app(settings(), transport=httpx.MockTransport(upstream), redis_client=redis)
    ) as client:
        response = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        cache_health = client.get("/cachez")
    assert response.status_code == 200
    assert upstream.calls == 1
    assert redis.get_count == redis.set_count == 1
    assert cache_health.status_code == 503
    assert cache_health.json() == {"status": "unavailable"}


def test_streaming_and_secondary_policy_bypass_cache() -> None:
    redis = MemoryRedis()
    upstream = MockUpstream()
    with TestClient(
        create_app(settings(), transport=httpx.MockTransport(upstream), redis_client=redis)
    ) as client:
        stream = client.post(
            "/v1/chat/completions", json={**REQUEST, "stream": True}, headers=auth(KEY_A)
        )
    assert stream.status_code == 200
    assert "data: [DONE]" in stream.text
    assert redis.get_count == redis.set_count == 0

    redis = MemoryRedis()
    upstream = MockUpstream()
    with TestClient(
        create_app(
            settings(secondary_mock_provider_url="http://secondary:8002"),
            transport=httpx.MockTransport(upstream),
            redis_client=redis,
        )
    ) as client:
        for _ in range(2):
            assert (
                client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A)).status_code
                == 200
            )
    assert upstream.calls == 2
    assert redis.get_count == redis.set_count == 0


def test_exact_key_is_deterministic_and_hides_prompt() -> None:
    request = ChatCompletionRequest.model_validate(REQUEST)
    tenant_a = TenantIdentity("tenant-a")
    tenant_b = TenantIdentity("tenant-b")
    first = exact_cache_key(tenant_a, request, provider_policy="policy-a")
    assert first == exact_cache_key(tenant_a, request, provider_policy="policy-a")
    assert first != exact_cache_key(tenant_b, request, provider_policy="policy-a")
    assert first != exact_cache_key(tenant_a, request, provider_policy="policy-b")
    assert first != exact_cache_key(
        tenant_a,
        ChatCompletionRequest.model_validate({**REQUEST, "model": "mock-v2"}),
        provider_policy="policy-a",
    )
    assert first != exact_cache_key(
        tenant_a,
        ChatCompletionRequest.model_validate({**REQUEST, "stream": True}),
        provider_policy="policy-a",
    )
    assert first != exact_cache_key(
        tenant_a,
        ChatCompletionRequest.model_validate(
            {**REQUEST, "messages": [{"role": "user", "content": "other"}]}
        ),
        provider_policy="policy-a",
    )
    assert "private prompt" not in first
    assert json.dumps(REQUEST) not in first


def test_rate_limit_counts_cache_hits_and_isolates_tenants() -> None:
    redis = MemoryRedis()
    upstream = MockUpstream()
    with TestClient(
        create_app(
            settings(rate_limit_requests=2),
            transport=httpx.MockTransport(upstream),
            redis_client=redis,
        )
    ) as client:
        first = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        hit = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        rejected = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        other = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_B))
        metrics = client.get("/metrics").text
    assert [item.status_code for item in (first, hit, rejected, other)] == [200, 200, 429, 200]
    assert first.headers["x-ratelimit-remaining"] == "1"
    assert hit.headers["x-ratelimit-remaining"] == "0"
    assert rejected.headers["retry-after"] == "60"
    assert rejected.json()["error"]["code"] == "rate_limit_exceeded"
    assert upstream.calls == 2
    assert "switchboard_rate_limit_rejections_total 1.0" in metrics
    assert 'switchboard_cache_operations_total{result="hit"} 1.0' in metrics
    assert KEY_A not in metrics and "private prompt" not in metrics


def test_rate_enforcement_outage_fails_closed_before_cache_or_provider() -> None:
    redis = MemoryRedis()
    redis.rate_fail = True
    upstream = MockUpstream()
    with TestClient(
        create_app(settings(), transport=httpx.MockTransport(upstream), redis_client=redis)
    ) as client:
        response = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rate_limit_unavailable"
    assert upstream.calls == redis.get_count == 0


def test_metrics_record_retries_fallback_and_bounded_provider_labels() -> None:
    redis = MemoryRedis()
    calls: list[str] = []

    def provider(upstream: httpx.Request) -> httpx.Response:
        calls.append(upstream.url.host)
        if upstream.url.host == "127.0.0.1":
            return httpx.Response(503)
        request = ChatCompletionRequest.model_validate_json(upstream.content)
        return httpx.Response(200, json=build_mock_chat_completion(request).model_dump(mode="json"))

    with TestClient(
        create_app(
            settings(secondary_mock_provider_url="http://secondary:8002"),
            transport=httpx.MockTransport(provider),
            redis_client=redis,
        )
    ) as client:
        response = client.post("/v1/chat/completions", json=REQUEST, headers=auth(KEY_A))
        metrics = client.get("/metrics").text
    assert response.status_code == 200
    assert calls == ["127.0.0.1", "127.0.0.1", "secondary"]
    assert 'switchboard_retries_total{provider="primary"} 1.0' in metrics
    assert "switchboard_fallbacks_total 1.0" in metrics
    assert (
        'switchboard_provider_failures_total{category="server",provider="primary"} 2.0' in metrics
    )
    assert 'switchboard_circuit_state{provider="primary",state="closed"} 1.0' in metrics
    assert 'provider="secondary"' in metrics
    assert "private prompt" not in metrics and KEY_A not in metrics
