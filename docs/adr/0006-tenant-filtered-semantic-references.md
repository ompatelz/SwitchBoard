# ADR 0006: Tenant-filtered semantic references

## Decision

Keep exact Redis lookup first. For a narrow server-approved fixture, search Qdrant only with mandatory authenticated-tenant, model, provider-policy, embedding-revision, semantic-policy, cache-schema, subject, and expiry filters. Validate returned metadata again. Store the response once in the exact Redis cache; Qdrant stores a vector, compatible scope metadata, expiration, and the Redis key. On a candidate, read and validate the exact response reference before reuse. Failures, corruption, and expiry fall through to the provider.

## Reasons and consequences

Tenant and version filters prevent an unrelated candidate from entering the acceptance decision. A matching subject and scoped Redis reference give stronger evidence than cosine score alone. The single response store avoids duplicate answer retention. A Redis eviction can leave a dangling vector until pruning; it causes a miss, never a served answer. Exact-cache schema version 2 deliberately invalidates older values. This is enabled only for reviewed synthetic fixture responses and remains off by default. Threshold calibration and held-out quality evidence remain separate work.
