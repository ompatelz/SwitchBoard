"""Unit tests for upstream SSE parsing, preflight, and response cleanup."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from switchboard.contracts import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionRequest,
    ChatMessage,
)
from switchboard.provider import (
    HttpxMockProvider,
    InvalidProviderResponseError,
    ProviderConnectionError,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FragmentedStream(httpx.AsyncByteStream):
    """Controlled upstream body that can split frames or fail between them."""

    def __init__(
        self,
        fragments: list[bytes],
        *,
        fail_after: int | None = None,
    ) -> None:
        self.fragments = fragments
        self.fail_after = fail_after
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index, fragment in enumerate(self.fragments):
            if self.fail_after == index:
                raise httpx.ReadError("injected mid-stream read failure")
            yield fragment
        if self.fail_after == len(self.fragments):
            raise httpx.ReadError("injected terminal read failure")

    async def aclose(self) -> None:
        self.closed = True


def request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="mock-v1",
        messages=[ChatMessage(role="user", content="stream this")],
        stream=True,
    )


def chunk_json(content: str) -> str:
    chunk = ChatCompletionChunk(
        id="chatcmpl-stream-test",
        created=1,
        model="mock-v1",
        choices=[ChatCompletionChunkChoice(delta=ChatCompletionDelta(content=content))],
    )
    return chunk.model_dump_json(exclude_none=True)


def sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode()


@pytest.mark.anyio
async def test_partial_sse_frames_are_reassembled_and_closed() -> None:
    """Arbitrary network fragmentation must not split logical SSE events."""
    body = sse(chunk_json("hello")) + sse("[DONE]")
    upstream = FragmentedStream([body[:3], body[3:17], body[17:-4], body[-4:]])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            stream=upstream,
        )

    async with httpx.AsyncClient(
        base_url="http://mock-provider",
        transport=httpx.MockTransport(handler),
    ) as client:
        provider = HttpxMockProvider(client)
        opened = await provider.open_stream(request(), request_id="partial-frames")
        events = [event async for event in opened]
        await opened.aclose()

    assert isinstance(events[0], ChatCompletionChunk)
    assert events[0].choices[0].delta.content == "hello"
    assert events[1] == "[DONE]"
    assert upstream.closed


@pytest.mark.anyio
async def test_invalid_first_event_fails_before_stream_is_returned() -> None:
    """Bad pre-first-byte data remains a stable HTTP error opportunity."""
    upstream = FragmentedStream([b"data: not-json\n\n"])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=upstream,
        )

    async with httpx.AsyncClient(
        base_url="http://mock-provider",
        transport=httpx.MockTransport(handler),
    ) as client:
        provider = HttpxMockProvider(client)
        with pytest.raises(InvalidProviderResponseError):
            await provider.open_stream(request(), request_id="invalid-first")

    assert upstream.closed


@pytest.mark.anyio
async def test_mid_stream_transport_failure_is_translated_and_closed() -> None:
    """A failure after the prefetched event is typed and releases the response."""
    upstream = FragmentedStream(
        [sse(chunk_json("partial")), sse(chunk_json("unreachable"))],
        fail_after=1,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=upstream,
        )

    async with httpx.AsyncClient(
        base_url="http://mock-provider",
        transport=httpx.MockTransport(handler),
    ) as client:
        opened = await HttpxMockProvider(client).open_stream(request(), request_id="mid-failure")
        iterator = aiter(opened)
        assert isinstance(await anext(iterator), ChatCompletionChunk)
        with pytest.raises(ProviderConnectionError):
            await anext(iterator)
        await opened.aclose()

    assert upstream.closed


@pytest.mark.anyio
async def test_missing_done_is_incomplete_not_successful() -> None:
    """EOF without [DONE] is an invalid partial stream, never a successful finish."""
    upstream = FragmentedStream([sse(chunk_json("partial"))])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=upstream,
        )

    async with httpx.AsyncClient(
        base_url="http://mock-provider",
        transport=httpx.MockTransport(handler),
    ) as client:
        opened = await HttpxMockProvider(client).open_stream(request(), request_id="missing-done")
        iterator = aiter(opened)
        await anext(iterator)
        with pytest.raises(InvalidProviderResponseError):
            await anext(iterator)
        await opened.aclose()

    assert upstream.closed


@pytest.mark.anyio
async def test_chunk_fixture_is_valid_json() -> None:
    """The helper emits normal JSON rather than a double-encoded string."""
    assert json.loads(chunk_json("hello"))["choices"][0]["delta"]["content"] == "hello"
