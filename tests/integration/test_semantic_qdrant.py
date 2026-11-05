"""Real Qdrant checks for tenant, version, subject, expiry, and schema isolation."""

import asyncio
import os
import time
import uuid
from dataclasses import replace

import httpx
import pytest

from switchboard.embedding_model import MODEL_DIMENSION
from switchboard.semantic_policy import SemanticScope
from switchboard.semantic_vectors import QdrantRepository, QdrantUnavailable

VECTOR = [1.0, *([0.0] * (MODEL_DIMENSION - 1))]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.qdrant
async def test_real_qdrant_filters_and_prunes() -> None:
    url = os.getenv("SWITCHBOARD_QDRANT_INTEGRATION_URL")
    if not url:
        pytest.skip("set SWITCHBOARD_QDRANT_INTEGRATION_URL for a running Qdrant")
    collection = f"switchboard_test_{uuid.uuid4().hex}"
    scope = SemanticScope("tenant-a", "static-definition-fixture-v1", "provider-a", "embed-v1")
    now = int(time.time())
    async with httpx.AsyncClient(base_url=url, timeout=5) as client:
        repo = QdrantRepository(client, collection=collection)
        try:
            await repo.ensure_ready()
            await repo.insert(scope, "heap", VECTOR, response_ref="response-a", expires_at=now + 30)
            await repo.insert(
                replace(scope, tenant_id="tenant-b"),
                "heap",
                VECTOR,
                response_ref="response-b",
                expires_at=now + 30,
            )
            own = await repo.search(scope, "heap", VECTOR, limit=3, now=now)
            assert len(own) == 1
            assert own[0].response_ref == "response-a"
            await asyncio.gather(
                *(
                    repo.insert(
                        scope,
                        "heap",
                        VECTOR,
                        response_ref=f"concurrent-{index}",
                        expires_at=now + 30,
                    )
                    for index in range(5)
                )
            )
            concurrent = await repo.search(scope, "heap", VECTOR, limit=10, now=now)
            assert len(concurrent) == 6
            assert [point.point_id for point in concurrent] == sorted(
                point.point_id for point in concurrent
            )
            assert (
                await repo.search(
                    replace(scope, tenant_id="tenant-c"), "heap", VECTOR, limit=3, now=now
                )
                == ()
            )
            assert (
                await repo.search(
                    replace(scope, embedding_model_version="embed-v2"),
                    "heap",
                    VECTOR,
                    limit=3,
                    now=now,
                )
                == ()
            )
            assert (
                await repo.search(
                    replace(scope, provider_policy="provider-b"), "heap", VECTOR, limit=3, now=now
                )
                == ()
            )
            assert (
                await repo.search(
                    replace(scope, semantic_policy_version=2), "heap", VECTOR, limit=3, now=now
                )
                == ()
            )
            assert (
                await repo.search(
                    replace(scope, cache_schema_version=2), "heap", VECTOR, limit=3, now=now
                )
                == ()
            )
            assert await repo.search(scope, "stack", VECTOR, limit=3, now=now) == ()
            assert await repo.search(scope, "heap", VECTOR, limit=3, now=now + 31) == ()
            await repo.prune_expired(now=now + 31)
            points = await client.post(
                f"/collections/{collection}/points/scroll",
                json={"limit": 10, "with_payload": False, "with_vector": False},
            )
            assert points.json()["result"]["points"] == []
        finally:
            await client.delete(f"/collections/{collection}")


@pytest.mark.anyio
@pytest.mark.qdrant
async def test_existing_wrong_dimension_fails_closed() -> None:
    url = os.getenv("SWITCHBOARD_QDRANT_INTEGRATION_URL")
    if not url:
        pytest.skip("set SWITCHBOARD_QDRANT_INTEGRATION_URL for a running Qdrant")
    collection = f"switchboard_test_{uuid.uuid4().hex}"
    async with httpx.AsyncClient(base_url=url, timeout=5) as client:
        try:
            created = await client.put(
                f"/collections/{collection}", json={"vectors": {"size": 3, "distance": "Cosine"}}
            )
            created.raise_for_status()
            with pytest.raises(QdrantUnavailable):
                await QdrantRepository(client, collection=collection).ensure_ready()
        finally:
            await client.delete(f"/collections/{collection}")
