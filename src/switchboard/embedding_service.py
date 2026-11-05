"""Isolated CPU embedding service; gateway never executes model inference."""

import asyncio
import math
import os
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Protocol, cast

from fastapi import FastAPI, Request
from pydantic import Field, model_validator
from starlette.responses import JSONResponse

from switchboard.contracts import StrictContract
from switchboard.embedding_model import MODEL_DIMENSION, MODEL_NAME, MODEL_REVISION, verify_manifest

MAX_BATCH = 16
MAX_TEXT_CHARS = 2048
MAX_TOTAL_CHARS = 8192
INFERENCE_TIMEOUT_SECONDS = 15.0


class EmbeddingRequest(StrictContract):
    texts: Annotated[list[str], Field(min_length=1, max_length=MAX_BATCH)]

    @model_validator(mode="after")
    def validate_texts(self) -> "EmbeddingRequest":
        if any(not text.strip() or len(text) > MAX_TEXT_CHARS for text in self.texts):
            raise ValueError("invalid embedding text")
        if sum(len(text) for text in self.texts) > MAX_TOTAL_CHARS:
            raise ValueError("embedding batch too large")
        return self


class EmbeddingResponse(StrictContract):
    model: str
    revision: str
    dimension: int
    normalized: bool
    vectors: list[list[float]]


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedEncoder:
    """Own one local ONNX session inside the embedding process."""

    def __init__(self, model_dir: Path) -> None:
        from fastembed import TextEmbedding

        if not model_dir.is_dir() or not (model_dir / "model_optimized.onnx").is_file():
            raise FileNotFoundError("pinned embedding model files are unavailable")
        verify_manifest(model_dir)
        self._model = TextEmbedding(
            model_name=MODEL_NAME,
            specific_model_path=str(model_dir),
            local_files_only=True,
            threads=2,
            providers=["CPUExecutionProvider"],
        )

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(list(texts), batch_size=MAX_BATCH)]


def _validate_vectors(vectors: list[list[float]], count: int) -> None:
    if len(vectors) != count:
        raise ValueError("embedding count mismatch")
    for vector in vectors:
        if len(vector) != MODEL_DIMENSION or not all(math.isfinite(value) for value in vector):
            raise ValueError("invalid embedding vector")
        if not math.isclose(
            math.sqrt(math.fsum(value * value for value in vector)), 1.0, abs_tol=1e-4
        ):
            raise ValueError("embedding vector is not normalized")


def create_app(
    *,
    model_dir: Path | None = None,
    encoder_factory: Callable[[], Encoder] | None = None,
    max_concurrency: int = 2,
) -> FastAPI:
    if max_concurrency < 1 or max_concurrency > 8:
        raise ValueError("invalid embedding concurrency")
    resolved_dir = model_dir or Path(
        os.getenv("SWITCHBOARD_EMBEDDING_MODEL_DIR", "/models/bge-small-en-v1.5")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.encoder = None
        try:
            factory = encoder_factory or (lambda: FastEmbedEncoder(resolved_dir))
            app.state.encoder = await asyncio.to_thread(factory)
        except (FileNotFoundError, ValueError, RuntimeError):
            pass
        app.state.capacity = asyncio.Semaphore(max_concurrency)
        app.state.inflight = set()
        yield
        pending = set(app.state.inflight)
        if pending:
            await asyncio.wait(pending, timeout=INFERENCE_TIMEOUT_SECONDS)

    app = FastAPI(title="Switchboard Embedding Worker", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        if request.app.state.encoder is None:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(
            content={"status": "ready", "model": MODEL_NAME, "revision": MODEL_REVISION}
        )

    @app.post("/embed", response_model=EmbeddingResponse)
    async def embed(body: EmbeddingRequest, request: Request) -> EmbeddingResponse | JSONResponse:
        encoder = cast(Encoder | None, request.app.state.encoder)
        if encoder is None:
            return JSONResponse(status_code=503, content={"code": "embedding_unavailable"})
        capacity = cast(asyncio.Semaphore, request.app.state.capacity)
        try:
            await asyncio.wait_for(capacity.acquire(), timeout=0.05)
        except TimeoutError:
            return JSONResponse(status_code=503, content={"code": "embedding_busy"})
        task = asyncio.create_task(asyncio.to_thread(encoder.encode, body.texts))
        inflight = cast(set[asyncio.Task[list[list[float]]]], request.app.state.inflight)
        inflight.add(task)

        def finish(done: asyncio.Task[list[list[float]]]) -> None:
            inflight.discard(done)
            capacity.release()
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finish)
        try:
            vectors = await asyncio.wait_for(
                asyncio.shield(task), timeout=INFERENCE_TIMEOUT_SECONDS
            )
            _validate_vectors(vectors, len(body.texts))
        except TimeoutError:
            return JSONResponse(status_code=503, content={"code": "embedding_timeout"})
        except (ValueError, RuntimeError, OSError):
            return JSONResponse(status_code=503, content={"code": "embedding_failed"})
        return EmbeddingResponse(
            model=MODEL_NAME,
            revision=MODEL_REVISION,
            dimension=MODEL_DIMENSION,
            normalized=True,
            vectors=vectors,
        )

    return app
