"""Shared HTTP contracts for Switchboard's public and test-provider boundaries."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ModelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
MessageContent = Annotated[str, StringConstraints(min_length=1, max_length=32_768)]
ChatMessages = Annotated[list["ChatMessage"], Field(min_length=1, max_length=64)]


class StrictContract(BaseModel):
    """Base for immutable boundary models that reject undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class HealthResponse(StrictContract):
    """Stable response returned by a service health endpoint."""

    status: Literal["ok"] = "ok"
    service: Literal["gateway", "mock-provider"]


class ReadinessResponse(StrictContract):
    """Response returned when the gateway and required upstream are ready."""

    status: Literal["ready"] = "ready"
    upstream: Literal["mock-provider"] = "mock-provider"


class ChatMessage(StrictContract):
    """One text-only message accepted by the Phase 1 Chat Completions subset."""

    role: Literal["system", "user", "assistant"]
    content: MessageContent

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        """Reject whitespace-only input without changing meaningful whitespace."""
        if not value.strip():
            raise ValueError("message content must contain non-whitespace text")
        return value


class ChatCompletionRequest(StrictContract):
    """Supported Phase 1A request subset; streaming arrives in Phase 1C."""

    model: ModelName
    messages: ChatMessages
    stream: Literal[False] = False


class AssistantMessage(StrictContract):
    """Assistant text returned in a non-streaming completion choice."""

    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(StrictContract):
    """The single deterministic choice returned by the Phase 1 mock."""

    index: Literal[0] = 0
    message: AssistantMessage
    finish_reason: Literal["stop"] = "stop"


class CompletionUsage(StrictContract):
    """OpenAI-shaped accounting populated with documented mock fixtures."""

    prompt_tokens: Annotated[int, Field(ge=0)]
    completion_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]


class ChatCompletionResponse(StrictContract):
    """OpenAI-compatible non-streaming response for the supported subset."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: Annotated[int, Field(ge=0)]
    model: str
    choices: Annotated[list[ChatCompletionChoice], Field(min_length=1, max_length=1)]
    usage: CompletionUsage


class ErrorDetail(StrictContract):
    """Non-sensitive error information returned by the public gateway."""

    message: str
    type: Literal["invalid_request_error", "provider_error"]
    code: str
    request_id: str


class ErrorResponse(StrictContract):
    """Stable public gateway error envelope."""

    error: ErrorDetail
