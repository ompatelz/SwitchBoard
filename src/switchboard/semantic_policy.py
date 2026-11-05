"""Pure, default-deny policy for a future guarded semantic cache."""

import re
from dataclasses import dataclass
from enum import StrEnum

from switchboard.auth import TenantIdentity
from switchboard.contracts import ChatCompletionRequest, ChatCompletionResponse

SEMANTIC_POLICY_VERSION = 1
SEMANTIC_CACHE_SCHEMA_VERSION = 1
_STATIC_DEFINITION = re.compile(r"^(?:What is|Define) (?:a |an )?[a-z][a-z -]{2,80}\?$", re.ASCII)
_UNSAFE_TERMS = re.compile(
    r"\b(?:current|today|now|latest|recent|new|price|weather|time|date|live|"
    r"not|never|without|except|different|versus|vs|output|format|json|table)\b",
    re.IGNORECASE | re.ASCII,
)


class EligibilityReason(StrEnum):
    ELIGIBLE = "eligible"
    UNTRUSTED_TASK = "untrusted_task"
    INCOMPATIBLE_PROVIDER = "incompatible_provider"
    INVALID_SCOPE = "invalid_scope"
    SENSITIVE_INPUT = "sensitive_input"
    STREAMING = "streaming"
    UNSUPPORTED_MODEL = "unsupported_model"
    MESSAGE_SHAPE = "message_shape"
    UNSAFE_PROMPT = "unsafe_prompt"
    RESPONSE_MISSING = "response_missing"
    RESPONSE_INCOMPATIBLE = "response_incompatible"


@dataclass(frozen=True)
class SemanticScope:
    """Server-derived isolation and invalidation fields, never client metadata."""

    tenant_id: str
    model: str
    provider_policy: str
    embedding_model_version: str
    semantic_policy_version: int = SEMANTIC_POLICY_VERSION
    cache_schema_version: int = SEMANTIC_CACHE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not all(
            (self.tenant_id, self.model, self.provider_policy, self.embedding_model_version)
        ):
            raise ValueError("semantic scope fields must be nonempty")


@dataclass(frozen=True)
class SemanticEligibilityContext:
    """Facts supplied by trusted gateway policy after authentication."""

    tenant: TenantIdentity
    provider_policy: str
    embedding_model_version: str
    supported_model: str = ""
    trusted_static_definition: bool = False
    provider_compatible: bool = False
    sensitive_input: bool = True


@dataclass(frozen=True)
class EligibilityDecision:
    reason: EligibilityReason
    scope: SemanticScope | None = None

    @property
    def eligible(self) -> bool:
        return self.reason is EligibilityReason.ELIGIBLE


def evaluate_lookup(
    request: ChatCompletionRequest, context: SemanticEligibilityContext
) -> EligibilityDecision:
    """Decide without I/O, embeddings, or user-provided tenant overrides."""
    if not context.trusted_static_definition:
        return EligibilityDecision(EligibilityReason.UNTRUSTED_TASK)
    if not context.provider_compatible or not context.provider_policy:
        return EligibilityDecision(EligibilityReason.INCOMPATIBLE_PROVIDER)
    if not context.tenant.tenant_id or not context.embedding_model_version:
        return EligibilityDecision(EligibilityReason.INVALID_SCOPE)
    if context.sensitive_input:
        return EligibilityDecision(EligibilityReason.SENSITIVE_INPUT)
    if request.stream:
        return EligibilityDecision(EligibilityReason.STREAMING)
    if not context.supported_model or request.model != context.supported_model:
        return EligibilityDecision(EligibilityReason.UNSUPPORTED_MODEL)
    if len(request.messages) != 1 or request.messages[0].role != "user":
        return EligibilityDecision(EligibilityReason.MESSAGE_SHAPE)
    prompt = request.messages[0].content
    if not _STATIC_DEFINITION.fullmatch(prompt) or _UNSAFE_TERMS.search(prompt):
        return EligibilityDecision(EligibilityReason.UNSAFE_PROMPT)
    return EligibilityDecision(
        EligibilityReason.ELIGIBLE,
        SemanticScope(
            tenant_id=context.tenant.tenant_id,
            model=request.model,
            provider_policy=context.provider_policy,
            embedding_model_version=context.embedding_model_version,
        ),
    )


def evaluate_storage(
    request: ChatCompletionRequest,
    context: SemanticEligibilityContext,
    response: ChatCompletionResponse | None,
) -> EligibilityDecision:
    """Require an eligible request and a complete compatible buffered response."""
    decision = evaluate_lookup(request, context)
    if not decision.eligible:
        return decision
    if response is None:
        return EligibilityDecision(EligibilityReason.RESPONSE_MISSING)
    if (
        response.model != request.model
        or len(response.choices) != 1
        or response.choices[0].finish_reason != "stop"
        or not response.choices[0].message.content.strip()
    ):
        return EligibilityDecision(EligibilityReason.RESPONSE_INCOMPATIBLE)
    return decision
