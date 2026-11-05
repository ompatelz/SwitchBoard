# Guarded semantic cache design

## Active boundary

Semantic reuse is disabled by default. The only live eligible model is the synthetic `static-definition-fixture-v1` fixture, with server-reviewed subjects `stack`, `linked list`, `heap`, and `hash table`. These subjects are disjoint from the original 20-pair hard-negative dataset. The separate four-pair fixture dataset has disjoint calibration and held-out subjects. Ordinary `mock-v1` responses depend on the exact prompt and bypass semantic reuse. The fixture demonstrates isolation and failure behavior; it supplies no production quality evidence.

After request validation, tenant authentication, and the Redis rate decision, the gateway checks the exact cache first. An exact miss runs the pure default-deny eligibility policy. Eligible buffered requests are embedded by the isolated worker, searched in Qdrant with server-derived filters, and accepted only above the configured score threshold with a matching subject digest and a valid same-scope exact Redis response reference. Otherwise the provider executes. Successful eligible provider responses are written once to Redis, and a vector plus metadata and exact-key reference is written to Qdrant. Streaming bypasses this path.

Qdrant search requires tenant digest, requested model, provider policy, embedding revision, semantic-policy version, cache-schema version, subject digest, and unexpired timestamp filters. The repository rechecks candidate payloads after search and sorts equal scores deterministically. Client input cannot choose a tenant or provider policy. Redis reference reads separately validate tenant, model, policy, and key form. Exact cache schema version 2 invalidates older entries. Neither Qdrant payload nor metrics contain raw prompts or answers.

The pinned BGE-small ONNX worker returns normalized 384-dimensional vectors. Qdrant uses cosine similarity. The fixture threshold `0.94` was selected by a reproducible calibration-only sweep and checked on disjoint held-out fixture subjects; see [the evaluation method](evaluation-methodology.md). It is not a general safe threshold. Similarity is a ranking signal, not proof that answers are interchangeable. The subject gate and response reference are additional hard requirements. The small fixture set cannot support a production quality or cost claim.

Entries use a 300-second exact-cache TTL. Qdrant candidates carry an expiry timestamp, are excluded at read time, and are pruned at startup and approximately hourly. A dangling, corrupt, expired, or mismatched Redis reference misses safely. Embedding or Qdrant failures are bounded bypasses to the provider after the rate decision. The worker and Qdrant are internal services on a trusted local network; their loopback ports are for development. Semantic metrics have fixed result labels without tenant or text content. See [ADR 0006](adr/0006-tenant-filtered-semantic-references.md).

## Alternatives and limits

- Duplicating response bodies in Qdrant would widen retention and consistency risk, so vectors reference the exact Redis entry.
- A broad text rule or client-declared safe category would allow changed entities, negation, freshness, or instructions; eligibility stays server-derived and narrow.
- Qdrant payload filters reduce candidate exposure, while a second payload and Redis-scope check guards against malformed or compromised results.
- Qdrant has no authentication in local Compose. A deployment needs private network access and an explicit service security decision.
