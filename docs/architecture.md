# Architecture

## Status and scope

This document describes only the code that exists in Phase 0A and the components planned for the immediately following Phase 0B. The broader product direction remains in [`BUILD_CONTRACT.md`](BUILD_CONTRACT.md); it is not an assertion that those systems already exist.

## Current architecture: Phase 0A

The current system is an installable Python distribution using a `src` layout:

```text
pyproject.toml
    |-- defines package metadata and quality-tool configuration
    |-- locks through uv.lock
    `-- builds src/switchboard as switchboard-gateway

src/switchboard/
    `-- exposes package metadata only

tests/
    `-- verifies a normal installed-package import
```

There is no running process, HTTP listener, request path, provider call, persistent store, cache, router, or evaluation workload yet.

## Immediately planned architecture: Phase 0B

Phase 0B will introduce two small ASGI applications:

```text
client
  | GET /healthz
  v
FastAPI gateway

test client
  | health check or deterministic test request
  v
FastAPI mock provider
```

The gateway and mock provider will remain separate applications so later integration tests can exercise a real upstream boundary. The mock will be deterministic so the same valid input produces the same response, keeping tests independent of paid services and nondeterministic model output.

The gateway will begin as a modular monolith. Modules will be created only when behavior requires them; Phase 0A does not create placeholder directories.

## Near-term request flow

Phase 0B will cover application startup, request validation, one small handler, and response serialization. It will not yet proxy Chat Completions, stream SSE data, or manage a shared upstream HTTP client. Shared HTTPX lifecycle and container wiring belong to Phase 0C.

## Deferred architecture

Redis, PostgreSQL, Qdrant, authentication, tenant budgets, semantic caching, policy routing, circuit breakers, metrics infrastructure, replay evaluation, and production deployment remain deferred. Their appearance in the build contract is roadmap context, not current implementation status.
