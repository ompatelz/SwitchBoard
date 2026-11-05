"""Guarded semantic lookup and insertion after the exact-cache boundary."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from switchboard.auth import TenantIdentity
from switchboard.contracts import ChatCompletionRequest, ChatCompletionResponse
from switchboard.embedding_client import EmbeddingClient, EmbeddingUnavailable
from switchboard.exact_cache import ExactCache
from switchboard.metrics import GatewayMetrics
from switchboard.semantic_policy import (
    EligibilityDecision,
    SemanticEligibilityContext,
    evaluate_lookup,
    evaluate_storage,
    static_definition_subject,
)
from switchboard.semantic_vectors import QdrantRepository, QdrantUnavailable


@dataclass(frozen=True)
class SemanticLookupResult:
    decision: EligibilityDecision
    response: ChatCompletionResponse | None = None
    vector: list[float] | None = None


class SemanticCache:
    """Use vector scores only after eligibility, scope, subject, and reference guards."""

    def __init__(
        self,
        *,
        embedder: EmbeddingClient,
        vectors: QdrantRepository,
        exact: ExactCache,
        metrics: GatewayMetrics,
        threshold: float,
        candidate_count: int,
        ttl_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not 0 <= threshold <= 1 or not 1 <= candidate_count <= 20 or ttl_seconds < 1:
            raise ValueError("invalid semantic cache settings")
        self.embedder = embedder
        self.vectors = vectors
        self.exact = exact
        self.metrics = metrics
        self.threshold = threshold
        self.candidate_count = candidate_count
        self.ttl_seconds = ttl_seconds
        self.clock = clock

    def _operation(self, result: str) -> None:
        self.metrics.semantic_operations.labels(result=result).inc()

    async def lookup(
        self, request: ChatCompletionRequest, context: SemanticEligibilityContext
    ) -> SemanticLookupResult:
        decision = evaluate_lookup(request, context)
        self.metrics.semantic_eligibility.labels(reason=decision.reason.value).inc()
        if not decision.eligible or decision.scope is None:
            self._operation("bypass")
            return SemanticLookupResult(decision)
        subject = static_definition_subject(request)
        if subject is None:
            self._operation("bypass")
            return SemanticLookupResult(decision)
        try:
            vector = (await self.embedder.embed([request.messages[0].content]))[0]
        except EmbeddingUnavailable:
            self._operation("embedding_error")
            return SemanticLookupResult(decision)
        try:
            candidates = await self.vectors.search(
                decision.scope,
                subject,
                vector,
                limit=self.candidate_count,
                now=int(self.clock()),
            )
        except QdrantUnavailable:
            self._operation("vector_error")
            return SemanticLookupResult(decision, vector=vector)
        if not candidates:
            self._operation("miss")
            return SemanticLookupResult(decision, vector=vector)
        for candidate in candidates:
            if candidate.score < self.threshold:
                self._operation("rejected")
                break
            response = await self.exact.read_reference(
                context.tenant, candidate.response_ref, model=request.model
            )
            if response is not None:
                self._operation("hit")
                return SemanticLookupResult(decision, response=response, vector=vector)
            self._operation("reference_missing")
        self._operation("miss")
        return SemanticLookupResult(decision, vector=vector)

    async def store(
        self,
        tenant: TenantIdentity,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
        context: SemanticEligibilityContext,
        lookup: SemanticLookupResult,
        response_ref: str | None,
    ) -> None:
        if lookup.vector is None or response_ref is None:
            return
        decision = evaluate_storage(request, context, response)
        if not decision.eligible or decision.scope is None or decision != lookup.decision:
            self._operation("store_bypass")
            return
        if tenant != context.tenant:
            self._operation("store_bypass")
            return
        subject = static_definition_subject(request)
        if subject is None:
            self._operation("store_bypass")
            return
        try:
            await self.vectors.insert(
                decision.scope,
                subject,
                lookup.vector,
                response_ref=response_ref,
                expires_at=int(self.clock()) + self.ttl_seconds,
            )
        except QdrantUnavailable:
            self._operation("vector_error")
            return
        self._operation("stored")
