# ADR 0003: Hash-configured tenant keys and fail-open exact Redis cache

- **Status:** Accepted for Phase 2B
- **Date:** 2026-11-04

## Context

Phase 2A has no tenant boundary. Exact response reuse is unsafe until a request has a stable tenant
identity and its cache key includes every supported response-affecting input.

## Decision

Completion requests require `Authorization: Bearer <key>`. Configuration maps bounded tenant IDs to
SHA-256 digests of high-entropy development keys; raw keys are supplied to clients separately and
are never committed. Missing, unknown, and revoked keys share the same 401 error. Empty key
configuration rejects all completions. The typed identity is injected into the route before cache
or provider work. This is authentication only: Phase 2B has no per-tenant authorization policy.

Use one lifespan-owned `redis.asyncio` client and pool with short connect and operation timeouts.
Its `aclose()` runs at shutdown. `/cachez` reports Redis health separately; `/readyz` remains about
the required mock provider. A Redis read/write failure bypasses caching and preserves an otherwise
allowed provider response. A corrupt entry is a miss. Redis is not an authority for authentication.

Only successful, buffered requests under a single configured provider are cacheable. Streaming and
secondary-provider policies bypass the cache. A canonical JSON object includes schema version,
tenant ID, validated request fields and defaults, and a digest of provider identity. The entire
object is SHA-256 hashed before forming the Redis key. Response JSON is validated against the strict
public model on read. Redis `SET EX` attaches the configured TTL atomically to the value.

## Consequences and alternatives

- Configured hashes keep raw development secrets out of the repository and server configuration;
  high-entropy generated keys are required because hashes do not protect weak passwords.
- There is no shared database for key administration. Revocation requires configuration update and
  process restart. This is a development credential system, not production identity management.
- The cache is fail-open because it is an optimization. Rate-limit enforcement will make a separate
  fail-open/fail-closed decision in Phase 2C.
- We bypass secondary-provider policies because a cached fallback result could be returned later
  when the primary is healthy. Provider-specific cache attribution is deferred.
- Concurrent misses can duplicate upstream work. A bounded singleflight design is deferred until
  measured need; this phase does not claim stampede prevention.
- Redis connection pooling and TTL are preferred over a process-local dictionary so entries can
  be shared by workers with server-enforced expiry. Cache correctness still depends on versioning
  and complete key inputs.

Revisit this ADR when adding response-affecting parameters, provider policy changes, paid
providers, or production credential management. Bump the cache schema when response semantics or
serialization change.
