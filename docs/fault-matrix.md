# Phase 2D fault-injection and cleanup gate

This is the tested mock-provider and local Redis gate, not a paid-provider or fleet reliability
claim. Deterministic injected errors run in-process; streaming and shutdown use real loopback
sockets; the Redis concurrency tests use a real Redis 7.4 container.

| Scenario | Injection and evidence | Observed contract or invariant |
| --- | --- | --- |
| Provider connection refusal | `test_transport_failures_are_bounded_and_translated`, `test_readiness_is_unavailable_when_upstream_fails` | Stable 502 completion or 503 readiness; no private exception text. |
| Connect, read, write, and pool timeout | `test_transport_failures_are_bounded_and_translated`, `test_deadline_bounds_slow_attempt` | Stable 504 and one overall pre-response deadline. |
| Provider 429 | `test_provider_statuses_remain_distinguishable`, `test_retry_after_header_is_parsed_conservatively` | Typed provider rate limit; valid bounded `Retry-After`. |
| Provider 500 and 503 | `test_provider_statuses_remain_distinguishable`, `test_retry_then_fallback_before_response` | Typed server failure, finite retries, optional pre-response fallback. |
| Invalid provider response | `test_invalid_provider_response_fails_safely`, `test_invalid_first_event_fails_before_stream_is_returned` | Stable 502; upstream body closed and not leaked. |
| Failure before first stream event | `test_real_network_stream_failures_preserve_honest_boundaries` | JSON 503 before public stream starts. |
| Failure after streaming begins | Same real-network test; `test_started_stream_never_uses_secondary` | Partial 200 closes without `[DONE]`, usage, retry, or provider splice. |
| Client cancellation/disconnect | `test_cancellation_escapes_without_retry`, `test_downstream_disconnect_closes_the_upstream_stream` | No retry; open upstream response closes. |
| Slow downstream consumer | `test_slow_consumer_does_not_pull_ahead_and_closes_upstream` | Another upstream event is not read until the downstream asks for it. |
| Redis unavailable | `test_rate_enforcement_outage_fails_closed_before_cache_or_provider`; live Compose Redis-stop probe and separate outage workload | 503 `rate_limit_unavailable` before cache/provider; no false success. |
| Isolated cache command failure | `test_redis_outage_fails_open_and_health_is_separate` | An allowed request reaches provider; `/cachez` reports failure. |
| Corrupt or expired cache entry | `test_ttl_expiry_and_corrupt_entry_return_to_provider`, `test_real_redis_set_ttl_hit_and_expiry` | Provider path is used; invalid cached data is not served. |
| Same request from two tenants | `test_tenant_isolation_exact_hit_and_input_change`, `test_rate_limit_counts_cache_hits_and_isolates_tenants` | Separate cache keys and rate counters. |
| Concurrent same-key cache misses | `test_concurrent_same_key_misses_can_duplicate_upstream_without_poisoning_cache` | Two calls can occur; later hit is valid. No singleflight claim. |
| Concurrent tenant rate decisions | `test_real_redis_rate_decisions_are_atomic_and_tenant_isolated` | Exactly 5 of 30 simultaneous decisions pass for a limit of 5; other tenant passes independently. |
| Upstream saturation | `test_second_request_is_rejected_without_queueing`, `test_stream_keeps_permit_until_close` | Immediate 503; no waiter queue; stream holds its permit. |
| Circuit open, half-open, failed and successful recovery | `test_breaker_transitions_with_fake_clock`, `test_breaker_cancelled_probe_releases_slot` | Deterministic local transitions and one probe slot. |
| Shutdown during in-flight work | `test_graceful_shutdown_waits_for_inflight_stream_then_cleans_up`, `test_lifespan_creates_and_closes_one_shared_client` | Uvicorn waits for the active stream; disconnect closes it and lifespan closes the shared HTTP client. |

## Guarded semantic fixture checks

`tests/integration/test_semantic_gateway.py` checks exact-first order, a compatible fixture hit,
cross-tenant forged-reference rejection, below-threshold bypass, embedding and Qdrant outage
fallback, streaming and ordinary-model bypass, and lifespan cleanup. The opt-in
`tests/integration/test_semantic_qdrant.py` runs against real Qdrant to check tenant, version,
subject, schema, expiry, and concurrent tie behavior. These are isolation and failure checks,
not a measured answer-quality gate.

The tests also check that authentication failure makes no upstream/cache request, input changes
cannot produce an incorrect exact hit, and API keys/prompts do not enter metric labels. Redis
`aclose()` is asserted in the tenant tests. Semaphore gauges return to zero after cancellation and
closure. The optional semantic cache creates one lifespan-owned expiry-pruning task; Uvicorn owns
the request ASGI tasks.

The slow-consumer test proves demand-driven iteration at the gateway generator boundary. It does
not measure kernel TCP-buffer size or prove a particular socket backpressure threshold. The
graceful-shutdown test covers Uvicorn's normal drain path after the client disconnects; forced
termination cannot promise application-level cleanup.
