# Switchboard

Switchboard is an OpenAI-compatible LLM inference gateway that will choose a safe, cost-effective way to fulfill each request and produce reproducible evidence about the quality, cost, latency, and reliability trade-offs behind that choice.

## Why Switchboard exists

LLM gateways can make routing and caching look simple while hiding difficult correctness questions: Was a cached answer actually safe to reuse? Did a retry duplicate cost? Did a streaming disconnect leak a connection? Did a cheaper route harm answer quality? Switchboard is designed to make those decisions explicit, testable, and measurable.

The project is a learning-focused, portfolio-grade backend and ML-systems implementation. Claims will be tied to reproducible tests and experiments rather than aspirational benchmark numbers.

## Current scope: Phase 0B

This branch currently provides the repository foundation and the first two ASGI applications:

- an installable `src/switchboard` Python package;
- a reproducible `uv` environment and committed lockfile;
- pytest, Ruff, and strict mypy configuration;
- GitHub Actions CI using the same local quality commands;
- safe example environment values;
- architecture, decision, build-contract, and status documentation;
- a FastAPI gateway with `GET /healthz`;
- a separate FastAPI mock provider with `GET /healthz` and `POST /generate`; and
- deterministic mock responses with strict Pydantic validation.

The gateway does not call the mock provider yet. Phase 0C will add the shared HTTP client lifecycle and container wiring.

## HTTP contracts

| Service | Method and path | Successful response |
| --- | --- | --- |
| Gateway | `GET /healthz` | `{"status":"ok","service":"gateway"}` |
| Mock provider | `GET /healthz` | `{"status":"ok","service":"mock-provider"}` |
| Mock provider | `POST /generate` | Stable `id`, `model`, and `text` derived from the validated request |

`POST /generate` accepts this deliberately small request:

```json
{
  "prompt": "Explain ASGI",
  "model": "mock-v1",
  "seed": 7
}
```

`prompt` is trimmed and must contain 1–4096 characters. `model` can only be `mock-v1`; `seed` must be an integer from 0 through 4,294,967,295. Unknown fields are rejected. Invalid requests currently use FastAPI's documented validation response with HTTP `422`; this is a mock-only contract, not an OpenAI error-compatibility claim.

## Explicit non-goals for Phase 0B

Phase 0B does **not** include:

- a `/v1/chat/completions` endpoint or any provider proxying;
- Redis, PostgreSQL, Qdrant, semantic caching, or model routing;
- gateway-to-provider HTTP calls, shared connection pooling, or SSE streaming;
- Docker images or Compose services;
- a dashboard, Kubernetes, Kafka, or paid-provider integration; or
- performance, cost-saving, or production-readiness claims.

## Verified status

The exact checks run for this subphase are recorded in [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md). Both applications have been started with Uvicorn and exercised over real localhost HTTP. The package and test suite also pass the locked lint, format, type, test, and build checks. GitHub-hosted CI remains unverified until this branch is pushed.

## Local development

Prerequisites:

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

Create the locked environment and install the project:

```powershell
uv sync --locked --all-groups
```

Run the complete local quality suite:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
uv build
```

Confirm that the installed package imports normally:

```powershell
uv run python -c "import switchboard; print(switchboard.__version__)"
```

Run the gateway:

```powershell
uv run uvicorn switchboard.gateway:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal, run the mock provider:

```powershell
uv run uvicorn switchboard.mock_provider:create_app --factory --host 127.0.0.1 --port 8001
```

Exercise both services:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8001/healthz
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8001/generate `
  -ContentType application/json `
  -Body '{"prompt":"Explain ASGI","model":"mock-v1","seed":7}'
```

Copy `.env.example` to `.env` only when local configuration is needed. Never commit `.env` or real credentials.

## Project documents

- [`docs/BUILD_CONTRACT.md`](docs/BUILD_CONTRACT.md) — project source of truth supplied by the owner
- [`docs/architecture.md`](docs/architecture.md) — current and immediately planned architecture
- [`docs/adr/0001-python-fastapi-chat-completions.md`](docs/adr/0001-python-fastapi-chat-completions.md) — initial architecture decision
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — verified implementation status and handoff log
