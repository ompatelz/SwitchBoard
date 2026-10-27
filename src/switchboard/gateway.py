"""Minimal Switchboard gateway application and upstream lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from switchboard import __version__
from switchboard.config import GatewaySettings
from switchboard.contracts import HealthResponse, ReadinessResponse


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the client created by lifespan for the current application."""
    return cast(httpx.AsyncClient, request.app.state.http_client)


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
            timeout=resolved_settings.upstream_timeout_seconds,
            transport=transport,
        ) as client:
            application.state.http_client = client
            yield

    application = FastAPI(
        title="Switchboard Gateway",
        summary="Policy-aware LLM gateway under incremental development.",
        version=__version__,
        lifespan=lifespan,
    )

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

    return application
