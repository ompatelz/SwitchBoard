"""A slow downstream consumer must control when the next upstream event is read."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from switchboard.contracts import ChatCompletionChunk, ChatCompletionRequest, ChatMessage
from switchboard.gateway import stream_provider_events
from switchboard.mock_provider import build_mock_stream_chunks
from switchboard.provider import ChatStreamEvent


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class CountingStream:
    def __init__(self, events: list[ChatCompletionChunk]) -> None:
        self.events = events
        self.reads = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        for event in self.events:
            self.reads += 1
            yield event
        self.reads += 1
        yield "[DONE]"

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_slow_consumer_does_not_pull_ahead_and_closes_upstream() -> None:
    request = ChatCompletionRequest(
        model="mock-v1", messages=[ChatMessage(role="user", content="slow client")], stream=True
    )
    upstream = CountingStream(build_mock_stream_chunks(request))
    downstream = stream_provider_events(upstream)
    assert b"data: " in await anext(downstream)
    assert upstream.reads == 1
    await asyncio.sleep(0.02)
    assert upstream.reads == 1
    assert b"data: " in await anext(downstream)
    assert upstream.reads == 2
    await downstream.aclose()
    assert upstream.closed
