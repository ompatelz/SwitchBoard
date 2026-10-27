"""Deterministic upstream simulator for local development and tests."""

import hashlib
import json
from typing import Annotated, Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from switchboard import __version__
from switchboard.contracts import HealthResponse

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)]
Seed = Annotated[int, Field(ge=0, le=4_294_967_295)]


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


def create_app() -> FastAPI:
    """Create an isolated mock-provider application instance."""
    application = FastAPI(
        title="Switchboard Mock Provider",
        summary="Deterministic upstream simulator for Switchboard tests.",
        version=__version__,
    )

    @application.get(
        "/healthz",
        response_model=HealthResponse,
        summary="Check mock-provider process health",
        tags=["operations"],
    )
    async def healthz() -> HealthResponse:
        """Report that the mock-provider application can serve requests."""
        return HealthResponse(service="mock-provider")

    @application.post(
        "/generate",
        response_model=MockGenerationResponse,
        summary="Generate a deterministic test response",
        tags=["mock"],
    )
    async def generate(request: MockGenerationRequest) -> MockGenerationResponse:
        """Return the response derived from the validated request."""
        return build_mock_response(request)

    return application
