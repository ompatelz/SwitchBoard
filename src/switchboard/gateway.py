"""Minimal Switchboard gateway application and upstream lifecycle."""

import hashlib
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, Literal, cast

import httpx
import redis.asyncio as redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import ValidationError
from redis.exceptions import RedisError
from starlette.responses import JSONResponse, Response, StreamingResponse

from switchboard import __version__
from switchboard.auth import ApiKeyAuthenticator, TenantIdentity
from switchboard.capacity import ConcurrencyLimitError, UpstreamCapacity
from switchboard.config import GatewaySettings
from switchboard.contracts import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    ReadinessResponse,
)
from switchboard.exact_cache import AsyncCacheClient, ExactCache
from switchboard.metrics import GatewayMetrics, RequestMetricsMiddleware
from switchboard.provider import (
    ChatProvider,
    ChatProviderStream,
    HttpxMockProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRejectedRequestError,
    ProviderServerError,
    ProviderTimeoutError,
)
from switchboard.rate_limit import FixedWindowRateLimiter, RateLimitUnavailable
from switchboard.reliability import (
    CircuitBreaker,
    CircuitOpenError,
    ProviderCapabilities,
    ProviderRegistry,
    RegisteredProvider,
    ReliableProviders,
    RetryPolicy,
)
from switchboard.request_ids import RequestIdMiddleware

ErrorType = Literal[
    "invalid_request_error", "provider_error", "authentication_error", "rate_limit_error"
]


class GatewayError(Exception):
    """Expected public error with a stable status and non-sensitive description."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        error_type: ErrorType,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.error_type = error_type
        self.headers = headers or {}


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the client created by lifespan for the current application."""
    return cast(httpx.AsyncClient, request.app.state.http_client)


def get_chat_provider(request: Request) -> ChatProvider:
    """Return the provider adapter created for this application lifespan."""
    return cast(ChatProvider, request.app.state.chat_provider)


def get_tenant_identity(request: Request) -> TenantIdentity:
    """Authenticate before provider or cache work and inject typed identity."""
    authenticator = cast(ApiKeyAuthenticator, request.app.state.authenticator)
    tenant = authenticator.authenticate(request.headers.get("authorization"))
    if tenant is None:
        raise GatewayError(401, "invalid_api_key", "Invalid API key.", "authentication_error")
    return tenant


def get_exact_cache(request: Request) -> ExactCache | None:
    """Return the eligible process's cache; fallback policies bypass it."""
    return cast(ExactCache | None, request.app.state.exact_cache)


def get_rate_limiter(request: Request) -> FixedWindowRateLimiter:
    return cast(FixedWindowRateLimiter, request.app.state.rate_limiter)


def request_id_from(request: Request) -> str:
    """Read the request ID assigned by the outer ASGI middleware."""
    return cast(str, request.state.request_id)


def error_response(request: Request, error: GatewayError) -> JSONResponse:
    """Serialize the documented error envelope without internal exception details."""
    body = ErrorResponse(
        error=ErrorDetail(
            message=error.message,
            type=error.error_type,
            code=error.code,
            request_id=request_id_from(request),
        )
    )
    headers = dict(error.headers)
    if error.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=error.status_code, content=body.model_dump(mode="json"), headers=headers
    )


def provider_gateway_error(error: ProviderError) -> GatewayError:
    """Map one expected provider failure without exposing its internal details."""
    if isinstance(error, ProviderTimeoutError):
        return GatewayError(504, "provider_timeout", "The provider timed out.", "provider_error")
    if isinstance(error, CircuitOpenError):
        return GatewayError(
            503, "provider_unavailable", "The provider is unavailable.", "provider_error"
        )
    if isinstance(error, ProviderConnectionError):
        return GatewayError(
            502,
            "provider_connection_error",
            "The provider could not be reached.",
            "provider_error",
        )
    if isinstance(error, ProviderRateLimitError):
        return GatewayError(
            429,
            "provider_rate_limited",
            "The provider is rate limited.",
            "provider_error",
        )
    if isinstance(error, ProviderRejectedRequestError):
        return GatewayError(
            502,
            "provider_rejected_request",
            "The provider rejected the validated request.",
            "provider_error",
        )
    if isinstance(error, ProviderServerError):
        return GatewayError(
            503,
            "provider_unavailable",
            "The provider is unavailable.",
            "provider_error",
        )
    return GatewayError(
        502,
        "invalid_provider_response",
        "The provider returned an invalid response.",
        "provider_error",
    )


def encode_sse_event(event: ChatCompletionChunk | Literal["[DONE]"]) -> bytes:
    """Encode one validated stream event using OpenAI-compatible SSE framing."""
    if event == "[DONE]":
        return b"data: [DONE]\n\n"
    data = event.model_dump_json(exclude_none=True)
    return f"data: {data}\n\n".encode()


async def stream_provider_events(
    provider_stream: ChatProviderStream,
) -> AsyncGenerator[bytes]:
    """Forward under backpressure and close upstream on completion or cancellation."""
    try:
        try:
            async for event in provider_stream:
                yield encode_sse_event(event)
                if event == "[DONE]":
                    return
        except ProviderError:
            # Headers/output have started: terminate without [DONE], usage, or fallback.
            return
    finally:
        await provider_stream.aclose()


def create_app(
    settings: GatewaySettings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    redis_client: AsyncCacheClient | None = None,
) -> FastAPI:
    """Create an isolated gateway application instance."""
    resolved_settings = settings or GatewaySettings.from_env()
    provider_policy = hashlib.sha256(
        f"mock-v1:{resolved_settings.mock_provider_url}".encode()
    ).hexdigest()
    metrics = GatewayMetrics()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    base_url=str(resolved_settings.mock_provider_url),
                    timeout=resolved_settings.http_timeout(),
                    transport=transport,
                )
            )
            providers = {
                "primary": RegisteredProvider(
                    HttpxMockProvider(client),
                    ProviderCapabilities(),
                    CircuitBreaker(
                        failure_threshold=resolved_settings.circuit_failure_threshold,
                        recovery_seconds=resolved_settings.circuit_recovery_seconds,
                    ),
                )
            }
            secondary_name: str | None = None
            if resolved_settings.secondary_mock_provider_url is not None:
                secondary_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=str(resolved_settings.secondary_mock_provider_url),
                        timeout=resolved_settings.http_timeout(),
                        transport=transport,
                    )
                )
                providers["secondary"] = RegisteredProvider(
                    HttpxMockProvider(secondary_client),
                    ProviderCapabilities(),
                    CircuitBreaker(
                        failure_threshold=resolved_settings.circuit_failure_threshold,
                        recovery_seconds=resolved_settings.circuit_recovery_seconds,
                    ),
                )
                secondary_name = "secondary"
            application.state.http_client = client
            application.state.provider_registry = ProviderRegistry(providers)
            application.state.chat_provider = ReliableProviders(
                application.state.provider_registry,
                primary="primary",
                secondary=secondary_name,
                policy=RetryPolicy(
                    max_attempts=resolved_settings.provider_max_attempts,
                    deadline_seconds=resolved_settings.provider_deadline_seconds,
                ),
                capacity=UpstreamCapacity(resolved_settings.upstream_concurrency_limit, metrics),
                metrics=metrics,
            )
            application.state.authenticator = ApiKeyAuthenticator(
                resolved_settings.tenant_key_hashes, resolved_settings.revoked_key_hashes
            )
            cache_connection: AsyncCacheClient = redis_client or redis.from_url(
                str(resolved_settings.redis_url),
                decode_responses=False,
                socket_connect_timeout=resolved_settings.redis_timeout_seconds,
                socket_timeout=resolved_settings.redis_timeout_seconds,
                max_connections=20,
            )
            stack.push_async_callback(cache_connection.aclose)
            application.state.redis_client = cache_connection
            application.state.rate_limiter = FixedWindowRateLimiter(
                cache_connection,
                limit=resolved_settings.rate_limit_requests,
                window_seconds=resolved_settings.rate_limit_window_seconds,
            )
            application.state.exact_cache = (
                ExactCache(
                    cache_connection,
                    ttl_seconds=resolved_settings.cache_ttl_seconds,
                    provider_policy=provider_policy,
                    metrics=metrics,
                )
                if secondary_name is None
                else None
            )
            yield

    application = FastAPI(
        title="Switchboard Gateway",
        summary="Policy-aware LLM gateway under incremental development.",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(RequestIdMiddleware)
    application.add_middleware(RequestMetricsMiddleware, metrics=metrics)

    @application.exception_handler(GatewayError)
    async def handle_gateway_error(request: Request, exc: GatewayError) -> JSONResponse:
        """Turn expected gateway failures into the stable public envelope."""
        return error_response(request, exc)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Separate malformed JSON from structurally invalid requests."""
        malformed_json = any(error["type"] == "json_invalid" for error in exc.errors())
        if malformed_json:
            error = GatewayError(
                400,
                "invalid_json",
                "Request body is not valid JSON.",
                "invalid_request_error",
            )
        else:
            error = GatewayError(
                422,
                "invalid_request",
                "Request does not match the supported Chat Completions contract.",
                "invalid_request_error",
            )
        return error_response(request, error)

    @application.get(
        "/healthz",
        response_model=HealthResponse,
        summary="Check gateway process health",
        tags=["operations"],
    )
    async def healthz() -> HealthResponse:
        """Report that the gateway application can serve requests."""
        return HealthResponse(service="gateway")

    @application.get(
        "/readyz",
        response_model=ReadinessResponse,
        summary="Check gateway upstream readiness",
        tags=["operations"],
    )
    async def readyz(request: Request) -> ReadinessResponse:
        """Report readiness only when the configured mock provider is healthy."""
        client = get_http_client(request)

        try:
            response = await client.get("/healthz")
            response.raise_for_status()
            health = HealthResponse.model_validate(response.json())
            if health.service != "mock-provider":
                raise ValueError("configured upstream is not the mock provider")
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "mock_provider_unavailable"},
            ) from exc

        return ReadinessResponse()

    @application.get("/cachez", summary="Check optional Redis cache health", tags=["operations"])
    async def cachez(request: Request) -> JSONResponse:
        cache_connection = cast(AsyncCacheClient, request.app.state.redis_client)
        try:
            await cache_connection.ping()
        except (RedisError, TimeoutError, OSError):
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(content={"status": "ok"})

    @application.get(
        "/metrics", summary="Export process-local gateway metrics", tags=["operations"]
    )
    async def metrics_endpoint(request: Request) -> Response:
        registry = cast(ProviderRegistry, request.app.state.provider_registry)
        states = {
            name: registry.get(name, stream=False).breaker.state.value
            for name in ("primary", "secondary")
            if name == "primary" or resolved_settings.secondary_mock_provider_url is not None
        }
        return Response(metrics.export(states), media_type=CONTENT_TYPE_LATEST)

    @application.post(
        "/v1/chat/completions",
        response_model=ChatCompletionResponse,
        responses={
            status: {"model": ErrorResponse} for status in (400, 401, 422, 429, 502, 503, 504)
        },
        summary="Create one buffered or streaming Chat Completion",
        tags=["chat"],
    )
    async def chat_completions(
        request_body: ChatCompletionRequest,
        request: Request,
        response: Response,
        tenant: Annotated[TenantIdentity, Depends(get_tenant_identity)],
        limiter: Annotated[FixedWindowRateLimiter, Depends(get_rate_limiter)],
        provider: Annotated[ChatProvider, Depends(get_chat_provider)],
        cache: Annotated[ExactCache | None, Depends(get_exact_cache)],
    ) -> ChatCompletionResponse | StreamingResponse:
        """Validate, correlate, and forward one buffered or streaming completion."""
        try:
            decision = await limiter.decide(tenant)
        except RateLimitUnavailable as exc:
            raise GatewayError(
                503, "rate_limit_unavailable", "Request limits are unavailable.", "rate_limit_error"
            ) from exc
        rate_headers = {
            "X-RateLimit-Limit": str(limiter.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.reset_seconds),
        }
        if not decision.allowed:
            metrics.rate_rejections.inc()
            raise GatewayError(
                429,
                "rate_limit_exceeded",
                "Request rate limit exceeded.",
                "rate_limit_error",
                headers={**rate_headers, "Retry-After": str(max(1, decision.reset_seconds))},
            )
        for key, value in rate_headers.items():
            response.headers[key] = value
        try:
            if not request_body.stream:
                if cache is not None:
                    cached = await cache.lookup(tenant, request_body)
                    if cached is not None:
                        return cached
                else:
                    metrics.cache.labels(result="bypass").inc()
                completion = await provider.complete(
                    request_body, request_id=request_id_from(request)
                )
                if cache is not None:
                    await cache.store(tenant, request_body, completion)
                return completion
            metrics.cache.labels(result="bypass").inc()
            provider_stream = await provider.open_stream(
                request_body,
                request_id=request_id_from(request),
            )
        except ProviderError as exc:
            raise provider_gateway_error(exc) from exc
        except ConcurrencyLimitError as exc:
            raise GatewayError(
                503,
                "upstream_concurrency_exhausted",
                "Upstream capacity is full.",
                "provider_error",
            ) from exc

        return StreamingResponse(
            stream_provider_events(provider_stream),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                **rate_headers,
            },
        )

    return application
