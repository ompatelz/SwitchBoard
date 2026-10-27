# Architecture

## Status and scope

This document describes only the code that exists through Phase 0B and the components planned for the immediately following Phase 0C. The broader product direction remains in [`BUILD_CONTRACT.md`](BUILD_CONTRACT.md); it is not an assertion that those systems already exist.

## Current architecture: Phase 0B

The current system is an installable Python distribution containing two independent FastAPI/ASGI applications:

```text
client -- GET /healthz --> gateway application

test client -- GET /healthz --> mock-provider application
test client -- POST /generate --> validation --> SHA-256 derivation --> mock response
```

Uvicorn runs each application as a separate process. FastAPI routes requests and serializes responses; strict Pydantic models reject unknown or invalid fields. The mock response is a pure function of a canonical JSON representation of the validated request, so it has no dependency on randomness, time, network calls, or process-local state.

The gateway and mock provider do not communicate yet. There is no persistent store, cache, router, provider adapter, or evaluation workload.

## Application factories

`switchboard.gateway.create_app()` and `switchboard.mock_provider.create_app()` each return a new FastAPI instance. This keeps process construction explicit, avoids mutable global application state, and lets tests create isolated instances. Uvicorn receives the factory with `--factory` and owns the network listener and event loop.

## Current request flows

```text
gateway: GET /healthz
  -> route handler
  -> HealthResponse
  -> JSON 200

mock: POST /generate
  -> Pydantic validation
  -> canonical JSON serialization
  -> SHA-256 digest
  -> MockGenerationResponse
  -> JSON 200
```

Validation failure stops before response generation and produces FastAPI's HTTP 422 validation structure. Both applications also expose independent health routes.

## Immediately planned architecture: Phase 0C

Phase 0C will give the gateway one lifespan-managed `httpx.AsyncClient`, configure the mock-provider URL through the environment, add only the minimal upstream reachability path required for end-to-end proof, and run both processes with Docker Compose and health checks. It will not implement the full Chat Completions proxy or SSE streaming.

## Deferred architecture

Redis, PostgreSQL, Qdrant, authentication, tenant budgets, semantic caching, policy routing, circuit breakers, metrics infrastructure, replay evaluation, Chat Completions proxying, SSE, and production deployment remain deferred. Their appearance in the build contract is roadmap context, not current implementation status.
