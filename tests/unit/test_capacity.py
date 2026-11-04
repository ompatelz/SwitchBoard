"""Bounded upstream admission and cancellation-safe permits."""

import asyncio
from collections.abc import AsyncIterator
from typing import Literal

import pytest

from switchboard.capacity import ConcurrencyLimitError, UpstreamCapacity
from switchboard.contracts import ChatCompletionRequest, ChatCompletionResponse, ChatMessage
from switchboard.metrics import GatewayMetrics
from switchboard.mock_provider import build_mock_chat_completion
from switchboard.provider import ChatProviderStream
from switchboard.reliability import (
    CircuitBreaker,
    ProviderCapabilities,
    ProviderRegistry,
    RegisteredProvider,
    ReliableProviders,
    RetryPolicy,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def request(*, stream: bool = False) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="mock-v1", messages=[ChatMessage(role="user", content="capacity")], stream=stream
    )


class HoldingStream:
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[Literal["[DONE]"]]:
        yield "[DONE]"

    async def aclose(self) -> None:
        self.closed = True


class BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.stream: HoldingStream | None = None

    async def complete(
        self, body: ChatCompletionRequest, *, request_id: str
    ) -> ChatCompletionResponse:
        self.started.set()
        await self.release.wait()
        return build_mock_chat_completion(body)

    async def open_stream(
        self, body: ChatCompletionRequest, *, request_id: str
    ) -> ChatProviderStream:
        self.stream = HoldingStream()
        return self.stream


def runner(provider: BlockingProvider, metrics: GatewayMetrics) -> ReliableProviders:
    registry = ProviderRegistry(
        {"primary": RegisteredProvider(provider, ProviderCapabilities(), CircuitBreaker())}
    )
    return ReliableProviders(
        registry,
        primary="primary",
        secondary=None,
        policy=RetryPolicy(max_attempts=1, deadline_seconds=1),
        capacity=UpstreamCapacity(1, metrics),
        metrics=metrics,
    )


@pytest.mark.anyio
async def test_second_request_is_rejected_without_queueing() -> None:
    provider = BlockingProvider()
    metrics = GatewayMetrics()
    reliable = runner(provider, metrics)
    first = asyncio.create_task(reliable.complete(request(), request_id="first"))
    await provider.started.wait()
    with pytest.raises(ConcurrencyLimitError):
        await asyncio.wait_for(reliable.complete(request(), request_id="second"), timeout=0.1)
    provider.release.set()
    await first
    await reliable.complete(request(), request_id="third")
    exported = metrics.export({}).decode()
    assert "switchboard_upstream_inflight 0.0" in exported
    assert "switchboard_concurrency_rejections_total 1.0" in exported


@pytest.mark.anyio
async def test_cancelled_request_releases_permit() -> None:
    provider = BlockingProvider()
    metrics = GatewayMetrics()
    reliable = runner(provider, metrics)
    first = asyncio.create_task(reliable.complete(request(), request_id="first"))
    await provider.started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    provider.release.set()
    await reliable.complete(request(), request_id="next")
    assert "switchboard_upstream_inflight 0.0" in metrics.export({}).decode()


@pytest.mark.anyio
async def test_stream_keeps_permit_until_close() -> None:
    provider = BlockingProvider()
    metrics = GatewayMetrics()
    reliable = runner(provider, metrics)
    opened = await reliable.open_stream(request(stream=True), request_id="stream")
    with pytest.raises(ConcurrencyLimitError):
        await reliable.complete(request(), request_id="blocked")
    await opened.aclose()
    await opened.aclose()
    assert provider.stream is not None and provider.stream.closed
    provider.release.set()
    await reliable.complete(request(), request_id="next")
    assert "switchboard_upstream_inflight 0.0" in metrics.export({}).decode()
