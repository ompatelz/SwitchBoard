"""Minimal Switchboard gateway application and upstream lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal, cast

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.responses import JSONResponse

from switchboard import __version__
from switchboard.config import GatewaySettings
from switchboard.contracts import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    ReadinessResponse,
)
from switchboard.provider import (
    ChatProvider,
    HttpxMockProvider,
    InvalidProviderResponseError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderRejectedRequestError,
    ProviderServerError,
    ProviderTimeoutError,
)
from switchboard.request_ids import RequestIdMiddleware

ErrorType = Literal["invalid_request_error", "provider_error"]


class GatewayError(Exception):
    """Expected public error with a stable status and non-sensitive description."""

    def __init__(self, status_code: int, code: str, message: str, error_type: ErrorType) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.error_type = error_type


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the client created by lifespan for the current application."""
    return cast(httpx.AsyncClient, request.app.state.http_client)


def get_chat_provider(request: Request) -> ChatProvider:
    """Return the provider adapter created for this application lifespan."""
    return cast(ChatProvider, request.app.state.chat_provider)


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
    return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))


def create_app(
    settings: GatewaySettings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create an isolated gateway application instance."""
    resolved_settings = settings or GatewaySettings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            base_url=str(resolved_settings.mock_provider_url),
            timeout=resolved_settings.http_timeout(),
            transport=transport,
        ) as client:
            application.state.http_client = client
            application.state.chat_provider = HttpxMockProvider(client)
            yield

    application = FastAPI(
        title="Switchboard Gateway",
        summary="Policy-aware LLM gateway under incremental development.",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(RequestIdMiddleware)

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

    @application.post(
        "/v1/chat/completions",
        response_model=ChatCompletionResponse,
        responses={status: {"model": ErrorResponse} for status in (400, 422, 429, 502, 503, 504)},
        summary="Create one non-streaming Chat Completion",
        tags=["chat"],
    )
    async def chat_completions(
        request_body: ChatCompletionRequest,
        request: Request,
        provider: Annotated[ChatProvider, Depends(get_chat_provider)],
    ) -> ChatCompletionResponse:
        """Validate, correlate, forward, and validate one provider completion."""
        try:
            return await provider.complete(request_body, request_id=request_id_from(request))
        except ProviderTimeoutError as exc:
            raise GatewayError(
                504, "provider_timeout", "The provider timed out.", "provider_error"
            ) from exc
        except ProviderConnectionError as exc:
            raise GatewayError(
                502,
                "provider_connection_error",
                "The provider could not be reached.",
                "provider_error",
            ) from exc
        except ProviderRateLimitError as exc:
            raise GatewayError(
                429,
                "provider_rate_limited",
                "The provider is rate limited.",
                "provider_error",
            ) from exc
        except ProviderRejectedRequestError as exc:
            raise GatewayError(
                502,
                "provider_rejected_request",
                "The provider rejected the validated request.",
                "provider_error",
            ) from exc
        except ProviderServerError as exc:
            raise GatewayError(
                503,
                "provider_unavailable",
                "The provider is unavailable.",
                "provider_error",
            ) from exc
        except InvalidProviderResponseError as exc:
            raise GatewayError(
                502,
                "invalid_provider_response",
                "The provider returned an invalid response.",
                "provider_error",
            ) from exc

    return application
