# Guarded semantic cache design

## Implemented foundation

`semantic_policy.evaluate_lookup` is a pure default-deny decision. The gateway does not call it yet,
so live requests still use the existing exact Redis cache and provider path. The future integration
must run after validation, tenant authentication, request controls, and exact-cache lookup.

The policy requires trusted server-side classification as a static definition, a compatible single
provider policy, an explicit non-sensitive designation, non-streaming mode, a server-allowlisted model, exactly
one user text message, and a narrow definition-question syntax. Freshness, negation, and output-format
terms are rejected. Unknown tasks and missing trusted facts bypass. The public request contract
rejects tools, multimodal content, and unsupported parameters before this policy can run. This
syntax guard is deliberately incomplete: it does not prove that all accepted questions are safe.
The future retrieval gate must still compare compatible metadata, a calibrated score, and any
additional answer-equivalence rules; a high cosine score alone cannot authorize reuse.
The current `mock-v1` provider emits prompt-derived fixture text and is not allowlisted for semantic
reuse. Unit tests use an abstract evaluation model to exercise the policy only.

`evaluate_storage` repeats request eligibility and requires a nonempty successful buffered response
with the requested model and stop finish reason. Decisions return one finite `EligibilityReason`
code; bypasses have no scope and need no embedding. No raw prompt or answer is placed in a reason.

`SemanticScope` carries authenticated tenant ID, requested model, server-selected provider policy,
embedding-model version, semantic-policy version, and semantic-cache schema version. The embedding
version is a required input; the pinned worker model is now selected, but the gateway has not loaded
or called it. Every field must be
included in future vector filtering and response-reference compatibility checks. Client fields
cannot override tenant or policy scope. The scope has no raw prompt or answer.

## Isolated embedding capability

The [embedding service](embedding-service.md) now exists as an optional Compose service. It owns
the pinned local ONNX model, inference threads, bounded admission, and `/embed` contract. A typed
HTTP client with explicit timeout categories exists for the next integration step, but the gateway
does not instantiate it or send prompts. No semantic cache lookup is active. The model revision is
fixed, so a later vector collection must reject embeddings made by any other revision.

## Future storage and failure boundaries

Qdrant and gateway integration are deferred. Before connecting them, decide where response bodies
live, set a common TTL and deletion rule for vectors and response references, and reject dangling or
corrupt references. Search must apply server-controlled tenant and all version filters before
candidate acceptance. Embedding or vector failure must bypass to the provider after a valid rate
decision. Streaming stays on its existing path. Bounded, fixed-label metrics should count each
reason without placing tenant IDs or content in labels.

## Alternatives considered

- An LLM task classifier would introduce latency, cost, nondeterminism, and a new prompt-data path.
- A broad text-only rule would admit date, entity, numeric, and instruction changes that often
  require different answers.
- A client-declared safe category could be forged. Trusted classification must be derived on the
  server and remain default-deny until that derivation has its own evidence.

This foundation intentionally yields zero production semantic hits. It is an explicit safety
boundary, not an estimate of eventual cache coverage.
