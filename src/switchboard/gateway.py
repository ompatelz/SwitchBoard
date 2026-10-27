"""Minimal Switchboard gateway application."""

from fastapi import FastAPI

from switchboard import __version__
from switchboard.contracts import HealthResponse


def create_app() -> FastAPI:
    """Create an isolated gateway application instance."""
    application = FastAPI(
        title="Switchboard Gateway",
        summary="Policy-aware LLM gateway under incremental development.",
        version=__version__,
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

    return application
