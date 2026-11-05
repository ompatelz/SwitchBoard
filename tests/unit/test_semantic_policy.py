"""Every default-deny semantic decision has a stable bounded reason."""

from dataclasses import replace

import pytest

from switchboard.auth import TenantIdentity
from switchboard.contracts import ChatCompletionRequest, ChatCompletionResponse
from switchboard.semantic_policy import (
    EligibilityReason,
    SemanticEligibilityContext,
    evaluate_lookup,
    evaluate_storage,
    static_definition_subject,
)


def request(
    messages: list[dict[str, str]] | None = None, **overrides: object
) -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {
            "model": "evaluation-model-v1",
            "messages": messages or [{"role": "user", "content": "What is a stack?"}],
            **overrides,
        }
    )


def context(**overrides: object) -> SemanticEligibilityContext:
    values: dict[str, object] = {
        "tenant": TenantIdentity("tenant-a"),
        "provider_policy": "mock-primary-v1",
        "embedding_model_version": "test-embedding-v1",
        "supported_model": "evaluation-model-v1",
        "trusted_static_definition": True,
        "provider_compatible": True,
        "sensitive_input": False,
    }
    values.update(overrides)
    return SemanticEligibilityContext(**values)  # type: ignore[arg-type]


def response(**overrides: object) -> ChatCompletionResponse:
    return ChatCompletionResponse.model_validate(
        {
            "id": "fixture",
            "created": 1,
            "model": "evaluation-model-v1",
            "choices": [{"message": {"content": "A stack is last in, first out."}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 8, "total_tokens": 13},
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"trusted_static_definition": False}, EligibilityReason.UNTRUSTED_TASK),
        ({"provider_compatible": False}, EligibilityReason.INCOMPATIBLE_PROVIDER),
        ({"provider_policy": ""}, EligibilityReason.INCOMPATIBLE_PROVIDER),
        ({"embedding_model_version": ""}, EligibilityReason.INVALID_SCOPE),
        ({"tenant": TenantIdentity("")}, EligibilityReason.INVALID_SCOPE),
        ({"supported_model": ""}, EligibilityReason.UNSUPPORTED_MODEL),
        ({"sensitive_input": True}, EligibilityReason.SENSITIVE_INPUT),
    ],
)
def test_trusted_context_bypass(change: dict[str, object], reason: EligibilityReason) -> None:
    assert evaluate_lookup(request(), context(**change)).reason is reason


@pytest.mark.parametrize(
    ("input_request", "reason"),
    [
        (request(stream=True), EligibilityReason.STREAMING),
        (request(model="other-model"), EligibilityReason.UNSUPPORTED_MODEL),
        (
            request(
                [
                    {"role": "system", "content": "Be brief"},
                    {"role": "user", "content": "What is a queue?"},
                ]
            ),
            EligibilityReason.MESSAGE_SHAPE,
        ),
        (
            request([{"role": "assistant", "content": "What is a queue?"}]),
            EligibilityReason.MESSAGE_SHAPE,
        ),
        (
            request([{"role": "user", "content": "What is the latest price?"}]),
            EligibilityReason.UNSAFE_PROMPT,
        ),
        (
            request([{"role": "user", "content": "What is not a queue?"}]),
            EligibilityReason.UNSAFE_PROMPT,
        ),
        (
            request([{"role": "user", "content": "What is 2 meters?"}]),
            EligibilityReason.UNSAFE_PROMPT,
        ),
        (
            request([{"role": "user", "content": "Return a JSON table"}]),
            EligibilityReason.UNSAFE_PROMPT,
        ),
    ],
)
def test_request_bypass(input_request: ChatCompletionRequest, reason: EligibilityReason) -> None:
    decision = evaluate_lookup(input_request, context())
    assert decision.reason is reason
    assert decision.scope is None


def test_defaults_deny_without_any_embedding_work() -> None:
    decision = evaluate_lookup(
        request(), SemanticEligibilityContext(TenantIdentity("tenant-a"), "", "")
    )
    assert decision.reason is EligibilityReason.UNTRUSTED_TASK
    assert decision.scope is None


def test_eligible_scope_is_server_controlled_and_versioned() -> None:
    first = evaluate_lookup(request(), context())
    second = evaluate_lookup(request(), context())
    assert first == second
    assert first.eligible
    assert first.scope is not None
    assert first.scope.tenant_id == "tenant-a"
    assert first.scope.model == "evaluation-model-v1"
    assert first.scope.provider_policy == "mock-primary-v1"
    assert first.scope.embedding_model_version == "test-embedding-v1"
    assert first.scope.semantic_policy_version == 1
    assert first.scope.cache_schema_version == 1
    assert (
        evaluate_lookup(request(), context(tenant=TenantIdentity("tenant-b"))).scope != first.scope
    )
    assert (
        evaluate_lookup(request(), context(provider_policy="different-policy")).scope != first.scope
    )


def test_storage_requires_complete_compatible_success() -> None:
    assert evaluate_storage(request(), context(), None).reason is EligibilityReason.RESPONSE_MISSING
    assert (
        evaluate_storage(request(), context(), response(model="other-model")).reason
        is EligibilityReason.RESPONSE_INCOMPATIBLE
    )
    empty = response(choices=[{"message": {"content": " "}}])
    assert (
        evaluate_storage(request(), context(), empty).reason
        is EligibilityReason.RESPONSE_INCOMPATIBLE
    )
    assert evaluate_storage(request(), context(), response()).eligible
    assert (
        evaluate_storage(request(stream=True), context(), response()).reason
        is EligibilityReason.STREAMING
    )


def test_scope_is_immutable() -> None:
    scope = evaluate_lookup(request(), context()).scope
    assert scope is not None
    assert replace(scope, embedding_model_version="next-version") != scope


def test_only_reviewed_fixture_subjects_are_approved() -> None:
    assert static_definition_subject(request()) == "stack"
    assert (
        static_definition_subject(request([{"role": "user", "content": "Define a hash table?"}]))
        == "hash table"
    )
    assert (
        static_definition_subject(request([{"role": "user", "content": "Define a stack?"}]))
        == "stack"
    )
    assert (
        static_definition_subject(request([{"role": "user", "content": "What is a bank?"}])) is None
    )
    assert (
        static_definition_subject(
            request([{"role": "user", "content": "What is the latest queue?"}])
        )
        is None
    )
