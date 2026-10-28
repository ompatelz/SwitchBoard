"""Deterministic upstream simulator for local development and tests."""

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.responses import StreamingResponse

from switchboard import __version__
from switchboard.contracts import (
    AssistantMessage,
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompletionUsage,
    HealthResponse,
)
from switchboard.request_ids import RequestIdMiddleware

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)]
Seed = Annotated[int, Field(ge=0, le=4_294_967_295)]
MOCK_CREATED_TIMESTAMP = 1_700_000_000
MockStreamScenario = Literal[
    "normal",
    "delayed",
    "fail_before_first",
    "fail_after_chunks",
    "slow",
]
STREAM_SCENARIOS = {
    "normal",
    "delayed",
    "fail_before_first",
    "fail_after_chunks",
    "slow",
}


@dataclass
class MockStreamMetrics:
    """Mutable test instrumentation for mock stream resource lifetime."""

    active: int = 0
    closed: int = 0
    completed: int = 0
    cancelled: int = 0


class MockStreamStateResponse(BaseModel):
    """Observable mock-only counters used by real-network cleanup tests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active: int
    closed: int
    completed: int
    cancelled: int


class MockGenerationRequest(BaseModel):
    """Validated input for a deterministic mock generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: Prompt
    model: Literal["mock-v1"] = "mock-v1"
    seed: Seed = 0


class MockGenerationResponse(BaseModel):
    """Stable output derived only from the validated request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    model: Literal["mock-v1"]
    text: str


def build_mock_response(request: MockGenerationRequest) -> MockGenerationResponse:
    """Derive a repeatable response without randomness, time, or external state."""
    canonical_request = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()

    return MockGenerationResponse(
        id=f"mock-{digest[:24]}",
        model=request.model,
        text=f"Deterministic mock response {digest[:16]}",
    )


def build_mock_chat_completion(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Build an OpenAI-shaped completion using only deterministic input data."""
    digest = _chat_request_digest(request)
    content = f"Deterministic mock completion {digest[:16]}"

    # These stable counts are fixtures for contract tests, not tokenizer output.
    prompt_tokens = sum(len(message.content.split()) for message in request.messages)
    completion_tokens = len(content.split())

    return ChatCompletionResponse(
        id=f"chatcmpl-mock-{digest[:24]}",
        created=MOCK_CREATED_TIMESTAMP,
        model=request.model,
        choices=[
            ChatCompletionChoice(
                message=AssistantMessage(content=content),
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def _chat_request_digest(request: ChatCompletionRequest) -> str:
    """Hash semantic prompt input while normalizing transport mode."""
    request_data = request.model_dump(mode="json")
    request_data["stream"] = False
    canonical_request = json.dumps(
        request_data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()


def build_mock_stream_chunks(request: ChatCompletionRequest) -> list[ChatCompletionChunk]:
    """Create deterministic chunks whose content matches non-streaming output."""
    digest = _chat_request_digest(request)
    completion_id = f"chatcmpl-mock-{digest[:24]}"
    content = f"Deterministic mock completion {digest[:16]}"
    content_parts = [content[:14], content[14:31], content[31:]]

    def chunk(
        delta: ChatCompletionDelta,
        finish_reason: Literal["stop"] | None = None,
    ) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id=completion_id,
            created=MOCK_CREATED_TIMESTAMP,
            model=request.model,
            choices=[ChatCompletionChunkChoice(delta=delta, finish_reason=finish_reason)],
        )

    return [
        chunk(ChatCompletionDelta(role="assistant", content="")),
        *(chunk(ChatCompletionDelta(content=part)) for part in content_parts),
        chunk(ChatCompletionDelta(), finish_reason="stop"),
    ]


def _encode_mock_sse(chunk: ChatCompletionChunk | Literal["[DONE]"]) -> bytes:
    if chunk == "[DONE]":
        return b"data: [DONE]\n\n"
    return f"data: {chunk.model_dump_json(exclude_none=True)}\n\n".encode()


async def mock_stream_body(
    request: ChatCompletionRequest,
    scenario: MockStreamScenario,
    delay_seconds: float,
    metrics: MockStreamMetrics,
) -> AsyncIterator[bytes]:
    """Yield fragmented deterministic SSE and record every terminal path."""
    metrics.active += 1
    try:
        chunks = build_mock_stream_chunks(request)
        for index, chunk in enumerate(chunks):
            if scenario == "fail_after_chunks" and index == 2:
                raise RuntimeError("injected mock mid-stream failure")
            if scenario in {"delayed", "slow"}:
                await asyncio.sleep(delay_seconds)
            frame = _encode_mock_sse(chunk)
            split_at = min(7, len(frame))
            yield frame[:split_at]
            yield frame[split_at:]

        done = _encode_mock_sse("[DONE]")
        yield done[:5]
        yield done[5:]
        metrics.completed += 1
    except asyncio.CancelledError:
        metrics.cancelled += 1
        raise
    finally:
        metrics.active -= 1
        metrics.closed += 1


def create_app(
    *,
    stream_scenario: MockStreamScenario | None = None,
    stream_delay_seconds: float | None = None,
) -> FastAPI:
    """Create an isolated mock-provider application instance."""
    raw_scenario = stream_scenario or os.getenv("SWITCHBOARD_MOCK_STREAM_SCENARIO", "normal")
    if raw_scenario not in STREAM_SCENARIOS:
        raise ValueError("unsupported mock stream scenario")
    resolved_scenario = cast(MockStreamScenario, raw_scenario)
    default_delay = 0.2 if resolved_scenario == "slow" else 0.05
    resolved_delay = (
        stream_delay_seconds
        if stream_delay_seconds is not None
        else float(os.getenv("SWITCHBOARD_MOCK_STREAM_DELAY_SECONDS", str(default_delay)))
    )
    if resolved_delay < 0 or resolved_delay > 10:
        raise ValueError("mock stream delay must be between 0 and 10 seconds")

    application = FastAPI(
        title="Switchboard Mock Provider",
        summary="Deterministic upstream simulator for Switchboard tests.",
        version=__version__,
    )
    application.add_middleware(RequestIdMiddleware)
    application.state.stream_metrics = MockStreamMetrics()

    @application.get(
        "/healthz",
        response_model=HealthResponse,
        summary="Check mock-provider process health",
        tags=["operations"],
    )
    async def healthz() -> HealthResponse:
        """Report that the mock-provider application can serve requests."""
        return HealthResponse(service="mock-provider")

    @application.get(
        "/stream-state",
        response_model=MockStreamStateResponse,
        summary="Inspect mock streaming resource counters",
        tags=["mock"],
    )
    async def stream_state() -> MockStreamStateResponse:
        """Expose test-only counters without request or response content."""
        metrics = cast(MockStreamMetrics, application.state.stream_metrics)
        return MockStreamStateResponse(
            active=metrics.active,
            closed=metrics.closed,
            completed=metrics.completed,
            cancelled=metrics.cancelled,
        )

    @application.post(
        "/generate",
        response_model=MockGenerationResponse,
        summary="Generate a deterministic test response",
        tags=["mock"],
    )
    async def generate(request: MockGenerationRequest) -> MockGenerationResponse:
        """Return the response derived from the validated request."""
        return build_mock_response(request)

    @application.post(
        "/v1/chat/completions",
        response_model=ChatCompletionResponse,
        summary="Generate a deterministic Chat Completion fixture",
        tags=["mock"],
    )
    async def chat_completions(
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse | StreamingResponse:
        """Return deterministic non-streaming JSON or fragmented SSE."""
        if not request.stream:
            return build_mock_chat_completion(request)
        if resolved_scenario == "fail_before_first":
            raise HTTPException(status_code=503, detail={"code": "injected_stream_failure"})
        metrics = cast(MockStreamMetrics, application.state.stream_metrics)
        return StreamingResponse(
            mock_stream_body(request, resolved_scenario, resolved_delay, metrics),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return application
