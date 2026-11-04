# Phase 2A failure model

The gateway currently speaks to deterministic mock providers only. A request is validated before
provider execution. The configured primary is tried first; an optional secondary mock can be used
only before a buffered response or the first validated streaming event is returned. Fallback can
change model behavior in a future real-provider integration, so it must remain explicit.

## Classification and retry

`provider.py` turns transport, timeout, 429, 4xx, 5xx, and malformed-response outcomes into typed
internal errors without copying upstream text. `is_retryable` is a pure function of the error type
and whether streaming output has started. Connection, timeout, 429, and 5xx are retryable for this
deterministic mock; permanent 4xx and invalid responses are not. Validation, cancellation, and
post-output stream failures never enter retry. A client-side SDK can retry separately; the checked-in
example disables those retries so gateway attempts remain visible.

Each provider gets at most `SWITCHBOARD_PROVIDER_MAX_ATTEMPTS` attempts (default 2, maximum 5).
Exponential backoff has full jitter between zero and a cap of one second. A valid `Retry-After`
delta or HTTP date may impose a minimum wait of up to 60 seconds; invalid and negative values are
ignored. A wait that cannot fit before the deadline is skipped. The entire pre-response operation,
including every retry and fallback, has one `SWITCHBOARD_PROVIDER_DEADLINE_SECONDS` deadline
(default 15). HTTPX connect/read/write/pool timeouts still bound individual I/O phases. A deadline
or task cancellation interrupts the active await. It never becomes another attempt.

Retries can amplify load and may duplicate cost when a real provider has accepted work before a
connection fails. This policy is enabled only for the deterministic, idempotent mock. Before adding
a paid provider, its request semantics and billing uncertainty need a separate decision.

## Circuit state

Each named provider has one process-local breaker in application lifespan state. Every worker has
independent state; there is no Redis sharing or claim of global consistency.

| State | Admission | Transition |
| --- | --- | --- |
| Closed | All calls | Count retryable failures; threshold 3 opens the circuit. Success resets count. |
| Open | No calls | After 10 seconds, the next call enters half-open. |
| Half-open | One probe at a time | Probe success closes; retryable failure reopens for another 10 seconds. |

These defaults are configurable. The clock is monotonic. A rejected call never occupies a probe
slot. Cancellation releases its slot without counting as a provider failure. Permanent rejection
also releases the slot without opening the circuit; a later successful probe closes it. A provider
that is open can be bypassed for the configured secondary. The breaker counts individual failed
attempts, so one request can reach the threshold. The state is memory only and resets at process
restart. It is not a distributed rate limiter or a provider health guarantee.

## Stream boundary and cleanup

The adapter validates upstream status, content type, and first SSE event before the gateway commits
HTTP 200. Retries and fallback are possible only in this preflight. The returned stream belongs to
one provider. Later failure terminates the stream without `[DONE]`; no retry, fallback, fabricated
usage, or second provider content is emitted. Its `finally` block closes the upstream HTTP response
on completion, failure, or downstream cancellation. A stream without `[DONE]` remains incomplete.
The overall retry deadline covers preflight, while individual HTTPX read timeouts continue to bound
subsequent streaming reads.

The application lifespan closes the primary and optional secondary HTTP clients. There is no Redis
in Phase 2A. HTTP status mapping remains non-sensitive and never includes credentials, provider
URLs, response bodies, or exception strings.

## Phase 2B authentication and cache failures

The configured key-hash map is process-local and read at startup. Empty, missing, invalid, and
revoked keys fail closed with the same 401 envelope before cache or upstream execution. Revocation
is applied by updating configuration and restarting workers; it is not a live global revocation
service. No raw key, prompt, response, or private Redis URL is logged by cache code.

The exact cache is a non-critical optimization. Redis connection, timeout, or command failure makes
lookup a miss and makes write a no-op. Invalid JSON, wrong schema version, and invalid response
shape are misses. A successful provider result is still returned when Redis write fails. `/cachez`
can return 503 while `/readyz` remains ready. Redis operations are awaited with a bounded socket
timeout and an application-lifespan-owned client pool; shutdown calls `aclose()`.

Only successful buffered requests with one configured mock provider enter the cache path. Streaming
and configured-secondary policies bypass it. Redis `SET EX` stores value and TTL in one command;
expiry is enforced by Redis, not an in-process timer. The key hashes tenant, provider identity,
request model, messages, and stream flag, plus a schema version. Changing a supported field or
provider policy changes the key. Concurrent misses may make duplicate provider calls; this phase
does not add a request queue, lock, or singleflight lease. Cache failure cannot broaden tenant
access because authentication remains independent of Redis.

## Deterministic injection

`mock_provider.create_app(failure_scenario=...)` supports `rate_limit`, `server_500`,
`server_503`, and `invalid` buffered or streaming preflight responses. The existing
`stream_scenario` supports `fail_before_first` and `fail_after_chunks`. Unit tests also inject
typed failures through fake adapters and control breaker time without sleeping. Connection refusal,
timeouts, and cancellation are injected at the HTTP transport or fake-adapter boundary.
