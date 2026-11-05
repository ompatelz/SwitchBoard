"""Bounded HTTP client for the isolated embedding worker; not on the gateway path yet."""

import math
from dataclasses import dataclass
from types import TracebackType

import httpx
from pydantic import ValidationError

from switchboard.embedding_model import MODEL_DIMENSION, MODEL_NAME, MODEL_REVISION
from switchboard.embedding_service import EmbeddingRequest, EmbeddingResponse


class EmbeddingUnavailable(Exception):
    """An embedding result was not safely available within the client boundary."""


@dataclass(frozen=True)
class EmbeddingClientSettings:
    base_url: str
    connect_timeout_seconds: float = 1.0
    read_timeout_seconds: float = 20.0
    write_timeout_seconds: float = 2.0
    pool_timeout_seconds: float = 1.0
    max_connections: int = 8

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("invalid embedding service URL")
        if (
            any(
                value <= 0
                for value in (
                    self.connect_timeout_seconds,
                    self.read_timeout_seconds,
                    self.write_timeout_seconds,
                    self.pool_timeout_seconds,
                )
            )
            or not 1 <= self.max_connections <= 64
        ):
            raise ValueError("invalid embedding client bounds")

    def timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect_timeout_seconds,
            read=self.read_timeout_seconds,
            write=self.write_timeout_seconds,
            pool=self.pool_timeout_seconds,
        )


class EmbeddingClient:
    """Own one pooled AsyncClient for an application's lifespan."""

    def __init__(
        self,
        settings: EmbeddingClientSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.timeout(),
            limits=httpx.Limits(max_connections=settings.max_connections),
            transport=transport,
        )

    async def __aenter__(self) -> "EmbeddingClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc_value, traceback)

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    async def embed(self, texts: list[str]) -> list[list[float]]:
        body = EmbeddingRequest(texts=texts)
        try:
            response = await self._client.post("/embed", json=body.model_dump(mode="json"))
            response.raise_for_status()
            result = EmbeddingResponse.model_validate(response.json())
            if (
                result.model != MODEL_NAME
                or result.revision != MODEL_REVISION
                or result.dimension != MODEL_DIMENSION
                or not result.normalized
                or len(result.vectors) != len(texts)
            ):
                raise EmbeddingUnavailable
            if any(
                len(vector) != MODEL_DIMENSION
                or not all(math.isfinite(value) for value in vector)
                or not math.isclose(
                    math.sqrt(math.fsum(value * value for value in vector)), 1.0, abs_tol=1e-4
                )
                for vector in result.vectors
            ):
                raise EmbeddingUnavailable
            return result.vectors
        except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
            raise EmbeddingUnavailable from exc
