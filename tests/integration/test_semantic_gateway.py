"""Deterministic gateway ordering and safe semantic fallback checks."""

import hashlib
import json
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from switchboard.config import GatewaySettings
from switchboard.contracts import ChatCompletionRequest
from switchboard.embedding_model import MODEL_DIMENSION, MODEL_NAME, MODEL_REVISION
from switchboard.gateway import create_app
from switchboard.mock_provider import build_mock_chat_completion, build_mock_stream_chunks
from switchboard.semantic_vectors import _KEYWORD_FIELDS

KEY_A = "semantic-tenant-a-test-key-0123456789"
KEY_B = "semantic-tenant-b-test-key-0123456789"
FIXTURE_MODEL = "static-definition-fixture-v1"
VECTOR = [1.0, *([0.0] * (MODEL_DIMENSION - 1))]


def settings(**overrides: object) -> GatewaySettings:
    return GatewaySettings.model_validate(
        {
            "tenant_key_hashes": {
                "tenant-a": hashlib.sha256(KEY_A.encode()).hexdigest(),
                "tenant-b": hashlib.sha256(KEY_B.encode()).hexdigest(),
            },
            "semantic_cache_enabled": True,
            "semantic_similarity_threshold": 0.95,
            **overrides,
        }
    )


def body(prompt: str, *, model: str = FIXTURE_MODEL, stream: bool = False) -> dict[str, object]:
    return {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": stream}


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.fail_set = False
        self.closed = False

    async def get(self, name: str) -> bytes | None:
        return self.values.get(name)

    async def set(self, name: str, value: bytes, *, ex: int) -> bool:
        if self.fail_set:
            raise RedisConnectionError("synthetic outage")
        self.values[name] = value
        return True

    async def ping(self) -> bool:
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        return [1, 60]

    async def aclose(self) -> None:
        self.closed = True


class EmbeddingTransport:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            raise httpx.ConnectError("synthetic outage")
        count = len(json.loads(request.content)["texts"])
        return httpx.Response(
            200,
            json={
                "model": MODEL_NAME,
                "revision": MODEL_REVISION,
                "dimension": MODEL_DIMENSION,
                "normalized": True,
                "vectors": [VECTOR for _ in range(count)],
            },
        )


class QdrantTransport:
    def __init__(self) -> None:
        self.points: list[dict[str, Any]] = []
        self.queries = 0
        self.fail_query = False
        self.corrupt_payload = False
        self.score = 1.0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/collections/switchboard_semantic_v1"):
            indexes = {field: {"data_type": "keyword"} for field in _KEYWORD_FIELDS}
            indexes["expires_at"] = {"data_type": "integer"}
            return httpx.Response(
                200,
                json={
                    "result": {
                        "config": {
                            "params": {"vectors": {"size": MODEL_DIMENSION, "distance": "Cosine"}}
                        },
                        "payload_schema": indexes,
                    }
                },
            )
        if request.method == "POST" and path.endswith("/points/delete"):
            return httpx.Response(200, json={"result": {}})
        if request.method == "PUT" and path.endswith("/points"):
            self.points.extend(json.loads(request.content)["points"])
            return httpx.Response(200, json={"result": {}})
        if request.method == "POST" and path.endswith("/points/query"):
            self.queries += 1
            if self.fail_query:
                raise httpx.ConnectError("synthetic outage")
            query = json.loads(request.content)
            conditions = query["filter"]["must"]
            matches = []
            for point in self.points:
                payload = point["payload"]
                if all(
                    payload.get(condition["key"]) == condition["match"]["value"]
                    if "match" in condition
                    else payload.get(condition["key"], 0) > condition["range"]["gt"]
                    for condition in conditions
                ):
                    returned = dict(payload)
                    if self.corrupt_payload:
                        returned["tenant_digest"] = "wrong-tenant"
                    matches.append({"id": point["id"], "score": self.score, "payload": returned})
            return httpx.Response(200, json={"result": {"points": matches[: query["limit"]]}})
        raise AssertionError(f"unexpected Qdrant call: {request.method} {path}")


class Upstream:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok", "service": "mock-provider"})
        self.calls += 1
        parsed = ChatCompletionRequest.model_validate(json.loads(request.content))
        if parsed.stream:
            chunks = build_mock_stream_chunks(parsed)
            payload = "".join(
                f"data: {chunk.model_dump_json(exclude_none=True)}\n\n" for chunk in chunks
            )
            return httpx.Response(
                200,
                content=f"{payload}data: [DONE]\n\n".encode(),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=build_mock_chat_completion(parsed).model_dump(mode="json"))


def clients(
    redis: MemoryRedis, embedding: EmbeddingTransport, qdrant: QdrantTransport, upstream: Upstream
) -> TestClient:
    app = create_app(
        settings(),
        transport=httpx.MockTransport(upstream),
        redis_client=redis,
        embedding_transport=httpx.MockTransport(embedding),
        qdrant_transport=httpx.MockTransport(qdrant),
    )
    return TestClient(app)


def test_exact_first_then_tenant_scoped_semantic_hit() -> None:
    redis, embedding, qdrant, upstream = (
        MemoryRedis(),
        EmbeddingTransport(),
        QdrantTransport(),
        Upstream(),
    )
    with clients(redis, embedding, qdrant, upstream) as client:
        source = client.post(
            "/v1/chat/completions", json=body("What is a stack?"), headers=auth(KEY_A)
        )
        target = client.post(
            "/v1/chat/completions", json=body("Define a stack?"), headers=auth(KEY_A)
        )
        again = client.post(
            "/v1/chat/completions", json=body("What is a stack?"), headers=auth(KEY_A)
        )
        other = client.post(
            "/v1/chat/completions", json=body("Define a stack?"), headers=auth(KEY_B)
        )
        metrics = client.get("/metrics").text
    assert source.status_code == target.status_code == again.status_code == other.status_code == 200
    assert source.json()["choices"] == target.json()["choices"]
    assert target.headers["X-Switchboard-Cache"] == "semantic"
    assert target.headers["X-Switchboard-Usage-Status"] == "source-response"
    assert "X-Switchboard-Cache" not in other.headers
    assert upstream.calls == 2
    assert embedding.calls == 3
    assert qdrant.queries == 3
    assert "tenant-a" not in metrics and KEY_A not in metrics and "What is a stack?" not in metrics
    assert redis.closed
    assert cast(Any, client.app).state.semantic_cache.embedder.is_closed
    assert cast(Any, client.app).state.semantic_cache.vectors.client.is_closed


@pytest.mark.parametrize("fault", ["embedding", "qdrant", "corrupt", "redis_write"])
def test_semantic_failure_reaches_provider(fault: str) -> None:
    redis, embedding, qdrant, upstream = (
        MemoryRedis(),
        EmbeddingTransport(),
        QdrantTransport(),
        Upstream(),
    )
    with clients(redis, embedding, qdrant, upstream) as client:
        redis.fail_set = fault == "redis_write"
        first = client.post(
            "/v1/chat/completions", json=body("What is a stack?"), headers=auth(KEY_A)
        )
        embedding.fail = fault == "embedding"
        qdrant.fail_query = fault == "qdrant"
        qdrant.corrupt_payload = fault == "corrupt"
        second = client.post(
            "/v1/chat/completions", json=body("Define a stack?"), headers=auth(KEY_A)
        )
    assert first.status_code == second.status_code == 200
    assert "X-Switchboard-Cache" not in second.headers
    assert upstream.calls == 2


def test_ordinary_mock_and_streaming_bypass_embeddings() -> None:
    redis, embedding, qdrant, upstream = (
        MemoryRedis(),
        EmbeddingTransport(),
        QdrantTransport(),
        Upstream(),
    )
    with clients(redis, embedding, qdrant, upstream) as client:
        ordinary = client.post(
            "/v1/chat/completions",
            json=body("What is a stack?", model="mock-v1"),
            headers=auth(KEY_A),
        )
        streaming = client.post(
            "/v1/chat/completions", json=body("What is a stack?", stream=True), headers=auth(KEY_A)
        )
    assert ordinary.status_code == streaming.status_code == 200
    assert embedding.calls == 0
    assert qdrant.queries == 0


def test_cross_tenant_reference_is_rejected_even_if_vector_payload_is_forged() -> None:
    redis, embedding, qdrant, upstream = (
        MemoryRedis(),
        EmbeddingTransport(),
        QdrantTransport(),
        Upstream(),
    )
    with clients(redis, embedding, qdrant, upstream) as client:
        client.post("/v1/chat/completions", json=body("What is a stack?"), headers=auth(KEY_A))
        point = qdrant.points[0]
        foreign_reference = point["payload"]["response_ref"]
        point["payload"]["tenant_digest"] = hashlib.sha256(b"tenant-b").hexdigest()
        second = client.post(
            "/v1/chat/completions", json=body("Define a stack?"), headers=auth(KEY_B)
        )
    assert second.status_code == 200
    assert "X-Switchboard-Cache" not in second.headers
    assert upstream.calls == 2
    assert foreign_reference in redis.values


def test_below_threshold_candidate_reaches_provider() -> None:
    redis, embedding, qdrant, upstream = (
        MemoryRedis(),
        EmbeddingTransport(),
        QdrantTransport(),
        Upstream(),
    )
    with clients(redis, embedding, qdrant, upstream) as client:
        source = client.post(
            "/v1/chat/completions", json=body("What is a stack?"), headers=auth(KEY_A)
        )
        assert source.status_code == 200
        qdrant.score = 0.5
        target = client.post(
            "/v1/chat/completions", json=body("Define a stack?"), headers=auth(KEY_A)
        )
    assert target.status_code == 200
    assert "X-Switchboard-Cache" not in target.headers
    assert upstream.calls == 2
