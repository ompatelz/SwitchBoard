"""Per-process Prometheus metrics with fixed, non-sensitive label sets."""

import time
from collections.abc import Callable
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from switchboard.provider import (
    InvalidProviderResponseError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRejectedRequestError,
    ProviderServerError,
    ProviderTimeoutError,
)


def failure_category(error: ProviderError) -> str:
    """Return one fixed label, never an upstream message or URL."""
    if isinstance(error, ProviderConnectionError):
        return "connection"
    if isinstance(error, ProviderTimeoutError):
        return "timeout"
    if isinstance(error, ProviderRateLimitError):
        return "rate_limit"
    if isinstance(error, ProviderServerError):
        return "server"
    if isinstance(error, ProviderRejectedRequestError):
        return "rejection"
    if isinstance(error, InvalidProviderResponseError):
        return "invalid_response"
    return "other"


class GatewayMetrics:
    """Own a private registry so test applications and workers never share labels."""

    def __init__(self) -> None:
        registry = CollectorRegistry()
        self.registry = registry
        self.requests = Counter(
            "switchboard_requests_total",
            "Completed gateway requests",
            ["status_class"],
            registry=registry,
        )
        self.request_duration = Histogram(
            "switchboard_request_duration_seconds", "Gateway request duration", registry=registry
        )
        self.provider_duration = Histogram(
            "switchboard_provider_duration_seconds",
            "Upstream attempt duration",
            ["provider"],
            registry=registry,
        )
        self.provider_failures = Counter(
            "switchboard_provider_failures_total",
            "Typed upstream failures",
            ["provider", "category"],
            registry=registry,
        )
        self.retries = Counter(
            "switchboard_retries_total", "Started retry attempts", ["provider"], registry=registry
        )
        self.fallbacks = Counter(
            "switchboard_fallbacks_total", "Started secondary-provider paths", registry=registry
        )
        self.circuit_state = Gauge(
            "switchboard_circuit_state",
            "One-hot local circuit state",
            ["provider", "state"],
            registry=registry,
        )
        self.cache = Counter(
            "switchboard_cache_operations_total", "Cache outcomes", ["result"], registry=registry
        )
        self.semantic_eligibility = Counter(
            "switchboard_semantic_eligibility_total",
            "Bounded semantic eligibility decisions",
            ["reason"],
            registry=registry,
        )
        self.semantic_operations = Counter(
            "switchboard_semantic_operations_total",
            "Guarded semantic cache outcomes",
            ["result"],
            registry=registry,
        )
        self.rate_rejections = Counter(
            "switchboard_rate_limit_rejections_total",
            "Tenant request-rate rejections",
            registry=registry,
        )
        self.upstream_inflight = Gauge(
            "switchboard_upstream_inflight", "Active upstream calls or streams", registry=registry
        )
        self.concurrency_rejections = Counter(
            "switchboard_concurrency_rejections_total",
            "Immediate upstream admission rejections",
            registry=registry,
        )

    def export(self, states: dict[str, str]) -> bytes:
        for provider, current in states.items():
            for state in ("closed", "open", "half_open"):
                self.circuit_state.labels(provider=provider, state=state).set(int(state == current))
        return generate_latest(self.registry)


class RequestMetricsMiddleware:
    """Observe completion after the final ASGI body, including streamed responses."""

    def __init__(
        self, app: Any, *, metrics: GatewayMetrics, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.app = app
        self.metrics = metrics
        self.clock = clock

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        started = self.clock()
        status = 500

        async def observed_send(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            self.metrics.requests.labels(status_class=f"{status // 100}xx").inc()
            self.metrics.request_duration.observe(max(0.0, self.clock() - started))
