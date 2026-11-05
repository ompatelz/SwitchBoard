"""The gateway-side client rejects incompatible results and closes its pool."""

import asyncio

import httpx
import pytest

from switchboard.embedding_client import (
    EmbeddingClient,
    EmbeddingClientSettings,
    EmbeddingUnavailable,
)
from switchboard.embedding_model import MODEL_DIMENSION, MODEL_NAME, MODEL_REVISION

VECTOR = [1.0, *([0.0] * (MODEL_DIMENSION - 1))]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def settings() -> EmbeddingClientSettings:
    return EmbeddingClientSettings(base_url="http://embedding-worker:8003")


@pytest.mark.anyio
async def test_client_contract_timeout_categories_and_cleanup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/embed"
        return httpx.Response(
            200,
            json={
                "model": MODEL_NAME,
                "revision": MODEL_REVISION,
                "dimension": MODEL_DIMENSION,
                "normalized": True,
                "vectors": [VECTOR],
            },
        )

    client = EmbeddingClient(settings(), transport=httpx.MockTransport(handler))
    assert client._client.timeout.connect == 1.0
    assert client._client.timeout.read == 20.0
    assert client._client.timeout.write == 2.0
    assert client._client.timeout.pool == 1.0
    async with client:
        assert await client.embed(["safe synthetic text"]) == [VECTOR]
    assert client.is_closed


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["outage", "wrong_revision", "wrong_dimension", "bad_norm"])
async def test_client_rejects_unavailable_or_corrupt_worker(fault: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if fault == "outage":
            raise httpx.ConnectError("unavailable")
        return httpx.Response(
            200,
            json={
                "model": MODEL_NAME,
                "revision": "other" if fault == "wrong_revision" else MODEL_REVISION,
                "dimension": 3 if fault == "wrong_dimension" else MODEL_DIMENSION,
                "normalized": True,
                "vectors": [[0.0] * MODEL_DIMENSION] if fault == "bad_norm" else [VECTOR],
            },
        )

    async with EmbeddingClient(settings(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(EmbeddingUnavailable):
            await client.embed(["safe synthetic text"])


@pytest.mark.anyio
async def test_client_cancellation_propagates() -> None:
    started = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        return httpx.Response(200)

    async with EmbeddingClient(settings(), transport=httpx.MockTransport(handler)) as client:
        task = asyncio.create_task(client.embed(["safe synthetic text"]))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
