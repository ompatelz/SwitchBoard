"""Deterministic retry, fallback, deadline, and circuit tests."""

import asyncio
from collections.abc import AsyncIterator
from typing import Literal

import httpx
import pytest

from switchboard.contracts import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
)
from switchboard.mock_provider import build_mock_chat_completion, build_mock_stream_chunks
from switchboard.provider import (
    ChatProviderStream,
    HttpxMockProvider,
    InvalidProviderResponseError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRejectedRequestError,
    ProviderServerError,
    ProviderTimeoutError,
)
from switchboard.reliability import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    ProviderCapabilities,
    ProviderRegistry,
    RegisteredProvider,
    ReliableProviders,
    RetryPolicy,
    is_retryable,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def request(*, stream: bool = False) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="mock-v1", messages=[ChatMessage(role="user", content="test")], stream=stream
    )


class FakeProvider:
    def __init__(
        self, results: list[ChatCompletionResponse | ProviderError | BaseException]
    ) -> None:
        self.results = results
        self.calls = 0

    async def complete(
        self, request: ChatCompletionRequest, *, request_id: str
    ) -> ChatCompletionResponse:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    async def open_stream(
        self, request: ChatCompletionRequest, *, request_id: str
    ) -> ChatProviderStream:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return FakeStream()


class FakeStream:
    def __aiter__(self) -> AsyncIterator[Literal["[DONE]"]]:
        return self._events()

    async def _events(self) -> AsyncIterator[Literal["[DONE]"]]:
        yield "[DONE]"

    async def aclose(self) -> None:
        pass


def runner(
    primary: FakeProvider,
    secondary: FakeProvider | None = None,
    *,
    max_attempts: int = 2,
    deadline: float = 1.0,
) -> ReliableProviders:
    providers = {"primary": RegisteredProvider(primary, ProviderCapabilities(), CircuitBreaker())}
    if secondary is not None:
        providers["secondary"] = RegisteredProvider(
            secondary, ProviderCapabilities(), CircuitBreaker()
        )
    return ReliableProviders(
        ProviderRegistry(providers),
        primary="primary",
        secondary="secondary" if secondary is not None else None,
        policy=RetryPolicy(
            max_attempts=max_attempts, base_delay_seconds=0, deadline_seconds=deadline
        ),
        jitter=lambda: 0,
    )


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (ProviderConnectionError(), True),
        (ProviderTimeoutError(), True),
        (ProviderRateLimitError(), True),
        (ProviderServerError(), True),
        (ProviderRejectedRequestError(), False),
        (InvalidProviderResponseError(), False),
    ],
)
def test_classification(error: ProviderError, retryable: bool) -> None:
    assert is_retryable(error) is retryable
    assert not is_retryable(error, stream_started=True)


@pytest.mark.anyio
async def test_retry_then_fallback_before_response() -> None:
    primary = FakeProvider([ProviderServerError(), ProviderConnectionError()])
    secondary = FakeProvider([ProviderTimeoutError(), ProviderRejectedRequestError()])
    with pytest.raises(ProviderRejectedRequestError):
        await runner(primary, secondary).complete(request(), request_id="test")
    assert primary.calls == 2
    assert secondary.calls == 2


@pytest.mark.anyio
async def test_fallback_returns_secondary_success() -> None:
    primary = FakeProvider([ProviderConnectionError(), ProviderServerError()])
    expected = build_mock_chat_completion(request())
    secondary = FakeProvider([expected])
    actual = await runner(primary, secondary).complete(request(), request_id="test")
    assert actual == expected
    assert (primary.calls, secondary.calls) == (2, 1)


@pytest.mark.anyio
async def test_permanent_failure_never_retries_or_falls_back() -> None:
    primary = FakeProvider([ProviderRejectedRequestError()])
    secondary = FakeProvider([])
    with pytest.raises(ProviderRejectedRequestError):
        await runner(primary, secondary).complete(request(), request_id="test")
    assert (primary.calls, secondary.calls) == (1, 0)


@pytest.mark.anyio
async def test_stream_preflight_falls_back_but_started_stream_is_owned_by_one_provider() -> None:
    primary = FakeProvider([ProviderServerError(), ProviderServerError()])
    secondary = FakeProvider([InvalidProviderResponseError()])
    with pytest.raises(InvalidProviderResponseError):
        await runner(primary, secondary).open_stream(request(stream=True), request_id="test")
    assert (primary.calls, secondary.calls) == (2, 1)


@pytest.mark.anyio
async def test_started_stream_never_uses_secondary() -> None:
    class FailingStream:
        def __aiter__(self) -> AsyncIterator[ChatCompletionChunk | Literal["[DONE]"]]:
            return self._events()

        async def _events(self) -> AsyncIterator[ChatCompletionChunk | Literal["[DONE]"]]:
            yield build_mock_stream_chunks(request(stream=True))[0]
            raise ProviderConnectionError

        async def aclose(self) -> None:
            pass

    class StreamingProvider(FakeProvider):
        async def open_stream(
            self, request: ChatCompletionRequest, *, request_id: str
        ) -> ChatProviderStream:
            self.calls += 1
            return FailingStream()

    primary = StreamingProvider([])
    secondary = FakeProvider([])
    opened = await runner(primary, secondary).open_stream(request(stream=True), request_id="test")
    events = aiter(opened)
    await anext(events)
    with pytest.raises(ProviderConnectionError):
        await anext(events)
    await opened.aclose()
    assert (primary.calls, secondary.calls) == (1, 0)


@pytest.mark.anyio
async def test_cancellation_escapes_without_retry() -> None:
    primary = FakeProvider([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await runner(primary).complete(request(), request_id="test")
    assert primary.calls == 1


@pytest.mark.anyio
async def test_deadline_bounds_slow_attempt() -> None:
    class SlowProvider(FakeProvider):
        async def complete(
            self, request: ChatCompletionRequest, *, request_id: str
        ) -> ChatCompletionResponse:
            self.calls += 1
            await asyncio.sleep(1)
            raise AssertionError("deadline failed")

    primary = SlowProvider([])
    with pytest.raises(ProviderTimeoutError):
        await runner(primary, deadline=0.01).complete(request(), request_id="test")
    assert primary.calls == 1


def test_retry_after_and_jitter() -> None:
    policy = RetryPolicy(base_delay_seconds=0.1, max_delay_seconds=1)
    assert policy.delay(1, ProviderRateLimitError(0.4), 0) == 0.4
    assert policy.delay(2, ProviderServerError(), 0.5) == 0.1


@pytest.mark.anyio
@pytest.mark.parametrize(("header", "expected"), [("2", 2.0), ("-1", None), ("garbage", None)])
async def test_retry_after_header_is_parsed_conservatively(
    header: str, expected: float | None
) -> None:
    def throttled(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": header})

    async with httpx.AsyncClient(
        base_url="http://mock-provider", transport=httpx.MockTransport(throttled)
    ) as client:
        with pytest.raises(ProviderRateLimitError) as failure:
            await HttpxMockProvider(client).complete(request(), request_id="test")
    assert failure.value.retry_after_seconds == expected


def test_registry_rejects_unsupported_capability() -> None:
    registry = ProviderRegistry(
        {
            "buffered": RegisteredProvider(
                FakeProvider([]), ProviderCapabilities(streaming_chat=False), CircuitBreaker()
            )
        }
    )
    with pytest.raises(ValueError, match="streaming"):
        registry.get("buffered", stream=True)


def test_breaker_transitions_with_fake_clock() -> None:
    now = [0.0]
    breaker = CircuitBreaker(
        failure_threshold=2, recovery_seconds=5, half_open_probes=1, clock=lambda: now[0]
    )
    assert not breaker.acquire()
    breaker.finish(probe=False, success=False)
    assert_state(breaker, CircuitState.CLOSED)
    assert not breaker.acquire()
    breaker.finish(probe=False, success=False)
    assert_state(breaker, CircuitState.OPEN)
    with pytest.raises(CircuitOpenError):
        breaker.acquire()
    now[0] = 5
    assert breaker.acquire()
    assert_state(breaker, CircuitState.HALF_OPEN)
    with pytest.raises(CircuitOpenError):
        breaker.acquire()
    breaker.finish(probe=True, success=False)
    assert_state(breaker, CircuitState.OPEN)
    now[0] = 10
    assert breaker.acquire()
    breaker.finish(probe=True, success=True)
    assert_state(breaker, CircuitState.CLOSED)
    assert breaker.probes_in_flight == 0


def test_breaker_cancelled_probe_releases_slot() -> None:
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=1, clock=lambda: now[0])
    breaker.finish(probe=False, success=False)
    now[0] = 1
    assert breaker.acquire()
    breaker.finish(probe=True, success=False, count_failure=False)
    assert breaker.probes_in_flight == 0


def assert_state(breaker: CircuitBreaker, state: CircuitState) -> None:
    assert breaker.state is state
