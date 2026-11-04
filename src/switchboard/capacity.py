"""Immediate, cancellation-safe admission to bounded upstream capacity."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable

from switchboard.metrics import GatewayMetrics, failure_category
from switchboard.provider import ChatProviderStream, ChatStreamEvent, ProviderError


class ConcurrencyLimitError(Exception):
    """No upstream slot was available; no task was queued."""


class UpstreamPermit:
    def __init__(self, semaphore: asyncio.Semaphore, metrics: GatewayMetrics | None) -> None:
        self._semaphore = semaphore
        self._metrics = metrics
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._semaphore.release()
            if self._metrics is not None:
                self._metrics.upstream_inflight.dec()


class UpstreamCapacity:
    """One process-local semaphore with immediate rejection and no waiter queue."""

    def __init__(self, limit: int, metrics: GatewayMetrics | None = None) -> None:
        if limit < 1:
            raise ValueError("upstream capacity must be positive")
        self._semaphore = asyncio.Semaphore(limit)
        self._metrics = metrics

    async def acquire(self) -> UpstreamPermit:
        # No await between the check and acquire; the free-slot path does not suspend.
        if self._semaphore.locked():
            if self._metrics is not None:
                self._metrics.concurrency_rejections.inc()
            raise ConcurrencyLimitError
        await self._semaphore.acquire()
        if self._metrics is not None:
            self._metrics.upstream_inflight.inc()
        return UpstreamPermit(self._semaphore, self._metrics)


class CapacityStream:
    """Keep one permit until the opened stream is closed."""

    def __init__(
        self,
        inner: ChatProviderStream,
        permit: UpstreamPermit | None,
        metrics: GatewayMetrics | None,
        provider: str,
        started: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.inner = inner
        self.permit = permit
        self.metrics = metrics
        self.provider = provider
        self.started = started
        self.clock = clock
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        try:
            async for event in self.inner:
                yield event
        except ProviderError as exc:
            if self.metrics is not None:
                self.metrics.provider_failures.labels(
                    provider=self.provider, category=failure_category(exc)
                ).inc()
            raise

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.inner.aclose()
        finally:
            if self.permit is not None:
                self.permit.release()
            if self.metrics is not None:
                self.metrics.provider_duration.labels(provider=self.provider).observe(
                    max(0.0, self.clock() - self.started)
                )
