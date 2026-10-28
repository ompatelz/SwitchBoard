# Architecture

## Status and scope

This document describes the merged Phase 0 foundation plus the accepted Phase 1 gateway MVP. The
broader product direction remains in [`BUILD_CONTRACT.md`](BUILD_CONTRACT.md); it is not an
assertion that those systems already exist.

## Current architecture: Phase 1 gateway MVP

The current system is an installable Python distribution containing two independent FastAPI/ASGI applications connected by one minimal readiness request:

```text
client -- GET /healthz --> gateway application
client -- GET /readyz --> gateway -- shared AsyncClient --> mock GET /healthz
OpenAI SDK or HTTP client -- POST /v1/chat/completions --> gateway validation --> provider adapter
  --> shared AsyncClient --> mock POST /v1/chat/completions --> validated response
client -- stream:true --> gateway preflight first SSE event --> async forwarding --> [DONE]

test client -- GET /healthz --> mock-provider application
test client -- POST /generate --> validation --> SHA-256 derivation --> mock response
test client -- POST /v1/chat/completions --> strict contract --> deterministic Chat Completion
```

Uvicorn runs each application as a separate process. FastAPI routes requests and serializes responses; strict Pydantic models reject unknown or invalid fields. The mock response is a pure function of a canonical JSON representation of the validated request, so it has no dependency on randomness, time, network calls, or process-local state.

The Chat Completions request and response models live in the shared boundary-contract module.
The gateway depends on the small `ChatProvider` protocol; its current `HttpxMockProvider` adapter
borrows the lifespan-managed client. There is no persistent store, cache, router, retry, fallback,
or evaluation workload.

```mermaid
flowchart LR
    C[Local client or smoke test] -->|GET /healthz| G[Gateway FastAPI app]
    C -->|GET /readyz| G
    C -->|POST /generate| M[Mock-provider FastAPI app]
    C -->|POST /v1/chat/completions| G
    G -->|buffered JSON or SSE through ChatProvider| M
    G -->|shared HTTPX client: GET /healthz| M
    L[Gateway lifespan] -->|create at startup| H[AsyncClient connection pool]
    H --> G
    L -->|close at shutdown| H
```

## Application factories

`switchboard.gateway.create_app()` and `switchboard.mock_provider.create_app()` each return a new FastAPI instance. This keeps process construction explicit, avoids mutable global application state, and lets tests create isolated instances. Uvicorn receives the factory with `--factory` and owns the network listener and event loop.

## Current request flows

```text
gateway: GET /healthz
  -> route handler
  -> HealthResponse
  -> JSON 200

gateway: POST /v1/chat/completions
  -> request-ID middleware
  -> strict ChatCompletionRequest validation
  -> injected ChatProvider protocol
  -> HttpxMockProvider using shared AsyncClient
  -> validated ChatCompletionResponse, validated SSE stream, or stable preflight error
  -> request ID response header

mock: POST /generate
  -> Pydantic validation
  -> canonical JSON serialization
  -> SHA-256 digest
  -> MockGenerationResponse
  -> JSON 200

mock: POST /v1/chat/completions
  -> strict ChatCompletionRequest validation
  -> canonical JSON serialization
  -> SHA-256 digest and controlled metadata fixtures
  -> ChatCompletionResponse JSON or deterministic fragmented SSE
  -> JSON 200 or role/content/finish chunks followed by [DONE]
```

Gateway validation failure stops before provider communication and produces the documented stable
error envelope. The mock provider retains FastAPI's direct 422 structure because it is a test
boundary, not the public gateway.

## Resource lifecycle

The gateway's lifespan context creates one `httpx.AsyncClient` before accepting requests, stores it
in application state, gives the provider adapter a borrowed reference, and closes it after the
lifespan exits. Readiness and completion requests reuse that client and connection pool. Buffered
provider responses are explicitly closed after validation. A streaming adapter owns its open
response, prefetched first event, and SSE parser until the gateway generator completes or is
cancelled. The generator yields only when the downstream server requests another item, naturally
coupling upstream reads to downstream backpressure. Its `finally` block closes the adapter on
success, provider failure, or client disconnect. Tests prove adapter/client identity,
response-body closure, real-socket cancellation cleanup, and final client shutdown without relying
on garbage collection.

Creating a client per request was rejected because it would discard connection pooling and make socket cleanup harder. CPU work and synchronous blocking calls remain prohibited on the event loop in later phases.

## Container topology

Both services use one locked, non-root image, built once from the mock-provider service definition and reused by the gateway. Compose starts the mock provider first, waits for its `/healthz`, then starts the gateway with `SWITCHBOARD_MOCK_PROVIDER_URL=http://mock-provider:8001`. Gateway health checks call `/readyz`, proving service discovery and upstream reachability rather than process liveness alone. Only ports 8000 and 8001 are published to host loopback.

## Streaming failure boundary

The provider adapter validates HTTP status, `text/event-stream`, and the first logical SSE event
before the public response starts. A failure there remains a normal JSON error. Once output starts,
HTTP status is committed: a later provider failure closes the partial response without `[DONE]`,
usage, retry, fallback, or cross-provider splicing. Missing `[DONE]` is therefore an explicit signal
that completion is unknown.

## SDK compatibility boundary

The standard OpenAI Python SDK is an external client of the public HTTP contract; it is not used
inside the gateway or provider adapter. The verified client points `base_url` at Switchboard's
local `/v1` prefix, supplies a placeholder key because the SDK requires one, disables SDK retries,
and exercises buffered and streaming Chat Completions. This proves the declared wire subset can be
consumed as typed SDK objects without coupling Switchboard's implementation to SDK internals.

Authentication is not implied by the placeholder key. Phase 1 accepts the SDK's Authorization
header but has no tenant identity or authorization policy. Those controls remain Phase 2 work.

## Deferred architecture

Redis, PostgreSQL, Qdrant, authentication, tenant budgets, semantic caching, policy routing,
circuit breakers, metrics infrastructure, replay evaluation, and production deployment remain
deferred. Their appearance in the build contract is roadmap context, not current implementation
status.
