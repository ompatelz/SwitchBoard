"""Embedding worker contract, event-loop isolation, and bounded cleanup."""

import asyncio
import math
import os
import threading
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import switchboard.embedding_service as service
from switchboard.embedding_model import MODEL_DIMENSION
from switchboard.embedding_service import create_app

VECTOR = [1.0, *([0.0] * (MODEL_DIMENSION - 1))]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class StaticEncoder:
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [VECTOR.copy() for _ in texts]


class BlockingEncoder:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self.started.set()
        if not self.release.wait(timeout=3):
            raise TimeoutError
        return [VECTOR.copy() for _ in texts]


class InvalidEncoder:
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * MODEL_DIMENSION for _ in texts]


def test_missing_model_is_alive_but_not_ready() -> None:
    app = create_app(model_dir=Path("definitely-missing-model-directory"))
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 503
        assert client.post("/embed", json={"texts": ["hello"]}).status_code == 503


@pytest.mark.parametrize(
    "texts",
    [[], [""], ["  "], ["x" * 2049], ["x"] * 17, ["x" * 1024] * 9],
)
def test_invalid_or_oversized_batch_is_rejected(texts: list[str]) -> None:
    app = create_app(encoder_factory=StaticEncoder)
    with TestClient(app) as client:
        assert client.post("/embed", json={"texts": texts}).status_code == 422
        assert (
            client.post("/embed", json={"texts": ["hello"], "extra": "ignored"}).status_code == 422
        )


def test_batch_metadata_and_normalization() -> None:
    app = create_app(encoder_factory=StaticEncoder)
    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200
        response = client.post("/embed", json={"texts": ["one", "two"]})
    assert response.status_code == 200
    data = response.json()
    assert data["dimension"] == MODEL_DIMENSION
    assert data["normalized"] is True
    assert len(data["vectors"]) == 2
    assert all(
        math.isclose(math.dist(vector, [0.0] * MODEL_DIMENSION), 1.0) for vector in data["vectors"]
    )


def test_invalid_model_output_fails_without_returning_a_vector() -> None:
    app = create_app(encoder_factory=InvalidEncoder)
    with TestClient(app) as client:
        response = client.post("/embed", json={"texts": ["one"]})
    assert response.status_code == 503
    assert response.json() == {"code": "embedding_failed"}


@pytest.mark.anyio
async def test_blocked_inference_keeps_event_loop_responsive_and_capacity_bounded() -> None:
    encoder = BlockingEncoder()
    app = create_app(encoder_factory=lambda: encoder, max_concurrency=1)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as client,
    ):
        first = asyncio.create_task(client.post("/embed", json={"texts": ["one"]}))
        try:
            assert await asyncio.to_thread(encoder.started.wait, 2)
            health = await asyncio.wait_for(client.get("/healthz"), timeout=0.5)
            assert health.status_code == 200
            busy = await client.post("/embed", json={"texts": ["two"]})
            assert busy.status_code == 503
            assert busy.json()["code"] == "embedding_busy"
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            encoder.release.set()
            for _ in range(30):
                if not app.state.inflight:
                    break
                await asyncio.sleep(0.01)
            assert not app.state.inflight
            recovered = await client.post("/embed", json={"texts": ["three"]})
            assert recovered.status_code == 200
        finally:
            encoder.release.set()


@pytest.mark.anyio
async def test_inference_deadline_keeps_slot_until_thread_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "INFERENCE_TIMEOUT_SECONDS", 0.05)
    encoder = BlockingEncoder()
    app = create_app(encoder_factory=lambda: encoder, max_concurrency=1)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as client,
    ):
        try:
            timed_out = await client.post("/embed", json={"texts": ["one"]})
            assert timed_out.status_code == 503
            assert timed_out.json() == {"code": "embedding_timeout"}
            assert app.state.inflight
            busy = await client.post("/embed", json={"texts": ["two"]})
            assert busy.json() == {"code": "embedding_busy"}
        finally:
            encoder.release.set()
        for _ in range(30):
            if not app.state.inflight:
                break
            await asyncio.sleep(0.01)
        assert not app.state.inflight


@pytest.mark.embedding
def test_real_pinned_model_is_stable_and_normalized() -> None:
    directory = os.getenv("SWITCHBOARD_EMBEDDING_MODEL_DIR")
    if not directory:
        pytest.skip("set SWITCHBOARD_EMBEDDING_MODEL_DIR to the pinned local model")
    app = create_app(model_dir=Path(directory))
    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200
        first = client.post("/embed", json={"texts": ["What is a queue?"]})
        second = client.post("/embed", json={"texts": ["What is a queue?"]})
    assert first.status_code == second.status_code == 200
    left, right = first.json()["vectors"][0], second.json()["vectors"][0]
    assert len(left) == MODEL_DIMENSION
    assert math.isclose(math.sqrt(math.fsum(x * x for x in left)), 1.0, abs_tol=1e-4)
    assert max(abs(a - b) for a, b in zip(left, right, strict=True)) < 1e-5
