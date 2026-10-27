"""Shared HTTP contracts for Switchboard's Phase 0 applications."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Stable response returned by a service health endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["gateway", "mock-provider"]


class ReadinessResponse(BaseModel):
    """Response returned when the gateway and required upstream are ready."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready"] = "ready"
    upstream: Literal["mock-provider"] = "mock-provider"
