"""Real-socket streaming tests for framing, failures, and disconnect cleanup."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from switchboard.config import GatewaySettings
from switchboard.contracts import ChatCompletionChunk
from switchboard.gateway import create_app as create_gateway_app
from switchboard.mock_provider import MockStreamStateResponse
from switchboard.mock_provider import create_app as create_mock_provider_app

STREAM_REQUEST = {
    "model": "mock-v1",
    "messages": [{"role": "user", "content": "Explain ASGI"}],
    "stream": True,
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def data_events(body: str) -> list[str]:
    """Extract data values from the one-line SSE subset Switchboard emits."""
    return [line[6:] for line in body.splitlines() if line.startswith("data: ")]


@asynccontextmanager
async def running_server(application: FastAPI) -> AsyncIterator[str]:
    """Serve one application on an OS-assigned loopback port."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    host, port = listener.getsockname()
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            log_level="critical",
            lifespan="on",
            access_log=False,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("test server did not start")
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@asynccontextmanager
async def running_stack(mock_application: FastAPI) -> AsyncIterator[tuple[str, str]]:
    """Serve mock provider and a gateway configured to call it."""
    async with running_server(mock_application) as mock_url:
        settings = GatewaySettings.model_validate({"mock_provider_url": mock_url})
        async with running_server(create_gateway_app(settings)) as gateway_url:
            yield gateway_url, mock_url


async def wait_for_closed_stream(mock_url: str) -> MockStreamStateResponse:
    """Wait until the mock generator's finally block has released ownership."""
    async with httpx.AsyncClient(timeout=2) as client:
        for _ in range(100):
            state = MockStreamStateResponse.model_validate(
                (await client.get(f"{mock_url}/stream-state")).json()
            )
            if state.active == 0 and state.closed >= 1:
                return state
            await asyncio.sleep(0.02)
    raise AssertionError("upstream stream did not close")


async def streaming_success_case() -> None:
    async with (
        running_stack(create_mock_provider_app()) as (gateway_url, _),
        httpx.AsyncClient(timeout=5) as client,
    ):
        streaming = await client.post(
            f"{gateway_url}/v1/chat/completions",
            json=STREAM_REQUEST,
        )
        non_streaming = await client.post(
            f"{gateway_url}/v1/chat/completions",
            json={**STREAM_REQUEST, "stream": False},
        )

    assert streaming.status_code == 200
    assert streaming.headers["content-type"].startswith("text/event-stream")
    assert streaming.headers["cache-control"] == "no-cache"
    assert streaming.headers["x-accel-buffering"] == "no"
    events = data_events(streaming.text)
    assert events[-1] == "[DONE]"
    chunks = [ChatCompletionChunk.model_validate_json(event) for event in events[:-1]]
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[-1].choices[0].finish_reason == "stop"
    content = "".join(chunk.choices[0].delta.content or "" for chunk in chunks)
    assert content == non_streaming.json()["choices"][0]["message"]["content"]
    assert all("usage" not in json.loads(event) for event in events[:-1])


@pytest.mark.anyio
async def test_real_network_streaming_is_openai_compatible() -> None:
    """A standard client receives validated chunks and a done sentinel."""
    await streaming_success_case()


async def failure_cases() -> None:
    async with running_stack(create_mock_provider_app(stream_scenario="fail_before_first")) as (
        gateway_url,
        _,
    ):
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{gateway_url}/v1/chat/completions",
                json=STREAM_REQUEST,
            )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_unavailable"
        assert not response.headers["content-type"].startswith("text/event-stream")

    async with running_stack(create_mock_provider_app(stream_scenario="fail_after_chunks")) as (
        gateway_url,
        mock_url,
    ):
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{gateway_url}/v1/chat/completions",
                json=STREAM_REQUEST,
            )
        events = data_events(response.text)
        assert response.status_code == 200
        assert events
        assert "[DONE]" not in events
        assert all("usage" not in json.loads(event) for event in events)
        state = await wait_for_closed_stream(mock_url)
        assert state.completed == 0


@pytest.mark.anyio
async def test_real_network_stream_failures_preserve_honest_boundaries() -> None:
    """Only pre-first failures can change status; partial output stays partial."""
    await failure_cases()


async def disconnect_case() -> None:
    mock_application = create_mock_provider_app(stream_scenario="slow", stream_delay_seconds=0.5)
    async with (
        running_stack(mock_application) as (gateway_url, mock_url),
        httpx.AsyncClient(timeout=5) as client,
    ):
        async with client.stream(
            "POST",
            f"{gateway_url}/v1/chat/completions",
            json=STREAM_REQUEST,
        ) as response:
            assert response.status_code == 200
            first_bytes = await anext(response.aiter_bytes())
            assert b"data: " in first_bytes
        state = await wait_for_closed_stream(mock_url)

    assert state.active == 0
    assert state.closed >= 1
    assert state.completed == 0


@pytest.mark.anyio
async def test_downstream_disconnect_closes_the_upstream_stream() -> None:
    """Early client departure cancels forwarding and releases the HTTP response."""
    await disconnect_case()
