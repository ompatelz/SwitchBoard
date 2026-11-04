# ADR 0002: Bounded mock-provider retry, fallback, and local circuit

- **Status:** Accepted for Phase 2A
- **Date:** 2026-11-04

## Context

Phase 1 makes one provider call and preserves honest streaming failure semantics. Phase 2A needs to
handle transient mock-provider failures without hiding unbounded work or splicing a started stream.

## Decision

Use a small registry of named adapters with explicit buffered and streaming capabilities. Run at
most two attempts per configured mock provider, with capped exponential backoff and full jitter,
under one 15-second pre-response deadline. Honor valid bounded `Retry-After` values. Only connection,
timeout, 429, and 5xx errors are retried. An optional secondary mock is tried after primary
retryable exhaustion or an open primary circuit, before any response output. Permanent rejection,
invalid response, validation failure, and cancellation do not trigger fallback.

Use one process-local closed/open/half-open breaker per provider. Three retryable failed attempts
open it. Ten seconds later, one half-open probe can run. A successful probe closes it; a retryable
failure reopens it. Cancellation releases the probe without marking provider health. HTTP clients
and breakers are owned by application lifespan. The gateway keeps the Phase 1 rule that a returned
stream is never retried or spliced after output starts.

## Alternatives and consequences

- Retrying every 4xx would repeat permanent failures and amplify load.
- A distributed breaker would require shared-state consistency and an outage policy not justified
  by the two-mock demonstration.
- Immediate fallback without retry could reduce latency but would make transient failure handling
  depend on secondary availability; the bounded policy is easier to inspect first.
- A task per attempt or hedged requests would create extra concurrent upstream work and uncertain
  cancellation, so attempts are sequential.

This policy is appropriate only for deterministic mock calls. Real providers may charge for work
that timed out locally, so retry and fallback require provider-specific idempotency and quality
review before production use. Revisit the limits after measured failure and latency data.
