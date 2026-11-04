# ADR 0004: Redis request windows, local capacity, and fixed-label metrics

Status: Accepted for Phase 2C (2026-11-04)

## Context

The gateway now authenticates tenants and may return an exact-cache hit without upstream work.
It needs a tenant request policy that works across gateway workers, a bound on active upstream
work, and measurements that do not disclose tenant content or create unbounded label sets.

## Decision

Use a Redis fixed window keyed by SHA-256 of tenant ID. An atomic Lua script increments the
counter, sets expiry on its first increment, and reads remaining TTL. Default policy is 120
requests per 60 seconds. Charge every authenticated completion before cache lookup; charge is not
refunded for a later error. Fail closed with 503 when Redis cannot give a trustworthy decision.
Return 429 and reset/remaining headers when the window is exhausted.

Use one `asyncio.Semaphore` per gateway worker, default capacity 32, around each upstream attempt.
Reject immediately when full. Release after buffered completion or failure; retain a streaming
permit until stream closure. Retry backoff does not hold a permit. The semaphore is not a global
quota and does not replace the HTTPX connection pool or the provider's own rate limits.

Use a private Prometheus registry per application process. Export counters for completed requests,
typed provider failures, retries, fallbacks, cache outcomes, and rejections; histograms for total
request and provider durations; gauges for active upstream permits and a local circuit snapshot.
Label only fixed provider names, finite error categories, cache outcomes, status classes, and
circuit states. Do not label tenant, API key, request ID, prompt, response, URL, or error message.

## Consequences and alternatives

Redis serializes each script execution, preventing a read-then-write race among workers sharing
that database. A fixed window is small and easy to inspect, but allows bursts around its boundary.
A sliding log or token bucket would smooth bursts at extra state and implementation cost. A
process-local counter would not enforce a shared tenant policy. Fail-open would allow unlimited
traffic during Redis failure; this decision favors enforcement over availability. The cache remains
fail-open only after a valid rate decision. Immediate capacity rejection avoids an unbounded waiter
queue, at the cost of returning 503 during short saturation spikes. Circuit and capacity state
reset on worker restart. Metrics are process-local and require external aggregation for fleet views.

Token limits are deferred because the deterministic mock's word counts are not a trustworthy
tokenizer or billing measure. A dashboard and distributed semaphore are outside Phase 2C.
