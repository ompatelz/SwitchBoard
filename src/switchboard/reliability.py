"""Bounded, process-local provider reliability for the deterministic mock."""

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import cast

from switchboard.contracts import ChatCompletionRequest, ChatCompletionResponse
from switchboard.provider import (
    ChatProvider,
    ChatProviderStream,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
)


@dataclass(frozen=True)
class ProviderCapabilities:
    """Only capabilities used by the current public contract."""

    buffered_chat: bool = True
    streaming_chat: bool = True


@dataclass(frozen=True)
class RegisteredProvider:
    adapter: ChatProvider
    capabilities: ProviderCapabilities
    breaker: "CircuitBreaker"


class ProviderRegistry:
    """Named, explicitly configured adapters; no dynamic plugin discovery."""

    def __init__(self, providers: dict[str, RegisteredProvider]) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = dict(providers)

    def get(self, name: str, *, stream: bool) -> RegisteredProvider:
        provider = self._providers[name]
        if stream and not provider.capabilities.streaming_chat:
            raise ValueError("provider does not support streaming chat")
        if not stream and not provider.capabilities.buffered_chat:
            raise ValueError("provider does not support buffered chat")
        return provider


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(ProviderError):
    """No call was made because this provider's local breaker is open."""


class CircuitBreaker:
    """One event-loop-local state machine with bounded half-open probes."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_seconds: float = 10.0,
        half_open_probes: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or recovery_seconds <= 0 or half_open_probes < 1:
            raise ValueError("invalid circuit-breaker limits")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.half_open_probes = half_open_probes
        self.clock = clock
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.opened_at = 0.0
        self.probes_in_flight = 0

    def acquire(self) -> bool:
        """Return whether this call owns a half-open probe slot."""
        if self.state is CircuitState.OPEN:
            if self.clock() - self.opened_at < self.recovery_seconds:
                raise CircuitOpenError
            self.state = CircuitState.HALF_OPEN
        if self.state is CircuitState.HALF_OPEN:
            if self.probes_in_flight >= self.half_open_probes:
                raise CircuitOpenError
            self.probes_in_flight += 1
            return True
        return False

    def finish(self, *, probe: bool, success: bool, count_failure: bool = True) -> None:
        """Release a probe and update state after a completed attempt."""
        if probe:
            self.probes_in_flight -= 1
        if not count_failure:
            return
        if success:
            self.failures = 0
            if self.state is CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
            return
        if self.state is CircuitState.HALF_OPEN:
            self._open()
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self.state = CircuitState.OPEN
        self.opened_at = self.clock()
        self.failures = 0


def is_retryable(error: ProviderError, *, stream_started: bool = False) -> bool:
    """Classify typed failures without matching public HTTP statuses or text."""
    return not stream_started and isinstance(
        error,
        (
            ProviderConnectionError,
            ProviderTimeoutError,
            ProviderRateLimitError,
            ProviderServerError,
        ),
    )


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0
    deadline_seconds: float = 15.0

    def __post_init__(self) -> None:
        if (
            self.max_attempts < 1
            or self.base_delay_seconds < 0
            or self.max_delay_seconds < self.base_delay_seconds
            or self.deadline_seconds <= 0
        ):
            raise ValueError("invalid retry limits")

    def delay(self, attempt: int, error: ProviderError, jitter: float) -> float:
        """Full jitter, except a valid Retry-After is a minimum wait."""
        cap = min(self.max_delay_seconds, self.base_delay_seconds * 2.0 ** (attempt - 1))
        delay = cap * jitter
        if isinstance(error, ProviderRateLimitError) and error.retry_after_seconds is not None:
            delay = max(delay, float(error.retry_after_seconds))
        return delay


class ReliableProviders:
    """Try the primary, then one optional secondary, within one deadline."""

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        primary: str,
        secondary: str | None,
        policy: RetryPolicy,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        registry.get(primary, stream=False)
        if secondary is not None:
            registry.get(secondary, stream=False)
        self.registry = registry
        self.primary = primary
        self.secondary = secondary
        self.policy = policy
        self.clock = clock
        self.jitter = jitter

    async def complete(
        self, request: ChatCompletionRequest, *, request_id: str
    ) -> ChatCompletionResponse:
        try:
            return cast(
                ChatCompletionResponse,
                await self._execute(request, request_id=request_id, stream=False),
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError from exc

    async def open_stream(
        self, request: ChatCompletionRequest, *, request_id: str
    ) -> ChatProviderStream:
        try:
            return cast(
                ChatProviderStream,
                await self._execute(request, request_id=request_id, stream=True),
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError from exc

    async def _execute(
        self, request: ChatCompletionRequest, *, request_id: str, stream: bool
    ) -> ChatCompletionResponse | ChatProviderStream:
        deadline = self.clock() + self.policy.deadline_seconds
        last_error: ProviderError | None = None
        async with asyncio.timeout(self.policy.deadline_seconds):
            for name in (self.primary, self.secondary):
                if name is None:
                    break
                registered = self.registry.get(name, stream=stream)
                for attempt in range(1, self.policy.max_attempts + 1):
                    if self.clock() >= deadline:
                        raise ProviderTimeoutError from last_error
                    try:
                        probe = registered.breaker.acquire()
                    except CircuitOpenError as exc:
                        last_error = exc
                        break
                    try:
                        if stream:
                            result: (
                                ChatCompletionResponse | ChatProviderStream
                            ) = await registered.adapter.open_stream(request, request_id=request_id)
                        else:
                            result = await registered.adapter.complete(
                                request, request_id=request_id
                            )
                    except ProviderError as exc:
                        registered.breaker.finish(
                            probe=probe, success=False, count_failure=is_retryable(exc)
                        )
                        last_error = exc
                        if not is_retryable(exc):
                            raise
                        if attempt == self.policy.max_attempts:
                            break
                        delay = self.policy.delay(attempt, exc, self.jitter())
                        if self.clock() + delay >= deadline:
                            raise ProviderTimeoutError from exc
                        await asyncio.sleep(delay)
                    except BaseException:
                        registered.breaker.finish(probe=probe, success=False, count_failure=False)
                        raise
                    else:
                        registered.breaker.finish(probe=probe, success=True)
                        return result
            if last_error is not None:
                raise last_error
            raise CircuitOpenError
