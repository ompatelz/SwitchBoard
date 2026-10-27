# ADR 0001: Python, FastAPI, and Chat Completions as the initial boundary

- **Status:** Accepted
- **Date:** 2026-10-27
- **Decision owners:** Switchboard maintainers

## Context

Switchboard needs an implementation language and an initial HTTP compatibility boundary before gateway behavior is built. The choice must support an async HTTP service, reproducible evaluation work, understandable code for a learning-focused project, and an incremental path from a small local demo to reliability and ML-systems experiments.

## Decision

### Python is exclusive for application and evaluation code

Python 3.12 or newer will be used for the gateway, mock provider, supporting workers, tests, and evaluation tooling. One language reduces context switching and lets the project share typed contracts and test utilities where that is useful. Python also has mature HTTP, data, and ML ecosystems.

This decision does not claim that Python is the fastest possible gateway language. I/O concurrency must be designed explicitly, CPU-bound work must stay off the event loop, and later benchmarks must separate gateway overhead from provider latency.

### FastAPI and ASGI are the HTTP foundation

FastAPI provides typed request/response validation, dependency injection, lifespan hooks, and direct access to Starlette/ASGI behavior. ASGI supports concurrent I/O and incremental response streaming, which the planned gateway needs for provider calls and SSE forwarding. Uvicorn will be the initial ASGI server, while FastAPI remains the application framework; the two roles are distinct.

### Start as a modular monolith

The gateway will start as one deployable Python application with internal modules separated by responsibility only when those responsibilities exist. The deterministic mock provider is a separate test boundary, not the beginning of a microservice fleet. This minimizes deployment and consistency complexity while preserving a path to isolate CPU-heavy embedding work later.

### Target a documented Chat Completions subset first

The first public compatibility target will be a deliberately limited subset of `POST /v1/chat/completions`. It is widely understood and provides the streaming and provider-translation problems the project intends to study. Unsupported parameters will be rejected or documented rather than silently accepted.

The newer Responses API is a future compatibility candidate, not part of the initial contract. “OpenAI-compatible” will always mean the documented subset, never complete endpoint or parameter parity.

## Alternatives considered

- **Go or Rust for the gateway:** stronger raw performance and concurrency characteristics, but would split application and evaluation languages and weaken the project's Python learning goal. Reconsider if measured Python overhead fails an explicit requirement after profiling.
- **Flask/WSGI:** simple and mature, but WSGI is a poor fit for native async streaming and cancellation behavior central to the project.
- **Django:** capable but adds application structure and features that the focused gateway does not currently need.
- **Multiple services from the start:** visually impressive but creates networking, deployment, and observability work before core correctness exists.
- **Responses API first:** strategically relevant, but expands the initial compatibility surface. It can be added after the Chat Completions subset is correct and measured.

## Consequences

- Async code is not automatically scalable; blocking work, cancellation, timeouts, pooling, and bounded concurrency need explicit design and tests.
- Python packaging and types are part of the product's engineering contract, hence the `src` layout, lockfile, linting, and strict type checks introduced in Phase 0A.
- A modular monolith keeps early changes understandable but requires discipline around module boundaries as behavior grows.
- Compatibility documentation and tests must be precise about supported fields and stream semantics.
- Provider SDK conveniences must not hide HTTP lifecycle or cancellation behavior that Switchboard needs to verify.

## Reversal criteria

Revisit this decision if reproducible benchmarks show that Python gateway overhead prevents a stated workload requirement after profiling and reasonable optimization; if a required provider capability cannot be represented safely by the selected Chat Completions subset; or if a component has a measured scaling or isolation need that cannot be met inside the modular monolith. Preference or architectural fashion alone is not sufficient evidence for reversal.
