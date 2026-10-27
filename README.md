# Switchboard

Switchboard is an OpenAI-compatible LLM inference gateway that will choose a safe, cost-effective way to fulfill each request and produce reproducible evidence about the quality, cost, latency, and reliability trade-offs behind that choice.

## Why Switchboard exists

LLM gateways can make routing and caching look simple while hiding difficult correctness questions: Was a cached answer actually safe to reuse? Did a retry duplicate cost? Did a streaming disconnect leak a connection? Did a cheaper route harm answer quality? Switchboard is designed to make those decisions explicit, testable, and measurable.

The project is a learning-focused, portfolio-grade backend and ML-systems implementation. Claims will be tied to reproducible tests and experiments rather than aspirational benchmark numbers.

## Current scope: Phase 0C

This branch currently provides the repository foundation and a runnable two-service slice:

- an installable `src/switchboard` Python package;
- a reproducible `uv` environment and committed lockfile;
- pytest, Ruff, and strict mypy configuration;
- GitHub Actions CI using the same local quality commands;
- safe example environment values;
- architecture, decision, build-contract, and status documentation;
- a FastAPI gateway with `GET /healthz`;
- a separate FastAPI mock provider with `GET /healthz` and `POST /generate`;
- deterministic mock responses with strict Pydantic validation;
- one lifespan-managed, pooled `httpx.AsyncClient` in the gateway;
- gateway `GET /readyz`, which verifies the configured mock provider over HTTP; and
- one non-root container image plus Docker Compose health checks for both services.

This remains infrastructure proof, not a Chat Completions proxy. Phase 0D will audit and document the complete Phase 0 slice before the branch is pushed and opened as a PR.

## HTTP contracts

| Service | Method and path | Successful response |
| --- | --- | --- |
| Gateway | `GET /healthz` | `{"status":"ok","service":"gateway"}` |
| Gateway | `GET /readyz` | `{"status":"ready","upstream":"mock-provider"}` when the mock provider is healthy |
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

## Explicit non-goals for Phase 0C

Phase 0C does **not** include:

- a `/v1/chat/completions` endpoint or any provider proxying;
- Redis, PostgreSQL, Qdrant, semantic caching, or model routing;
- Chat Completions forwarding, response proxying, retries, or SSE streaming;
- a dashboard, Kubernetes, Kafka, or paid-provider integration; or
- performance, cost-saving, or production-readiness claims.

## Verified status

The exact checks run for this subphase are recorded in [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md). Both applications have been exercised over local Uvicorn sockets and as healthy Docker Compose services. The gateway reached the mock provider through Compose DNS, the end-to-end smoke test passed, and Compose shut down both containers cleanly. GitHub-hosted CI remains unverified until this branch is pushed.

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
Invoke-RestMethod http://127.0.0.1:8000/readyz
Invoke-RestMethod http://127.0.0.1:8001/healthz
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8001/generate `
  -ContentType application/json `
  -Body '{"prompt":"Explain ASGI","model":"mock-v1","seed":7}'
```

## Docker Compose

Docker Desktop must be running. Build and wait for both health checks:

```powershell
docker compose -f deploy/compose.yaml up --build --wait --wait-timeout 180
```

Run the real end-to-end smoke test against the published ports:

```powershell
$env:SWITCHBOARD_E2E = "1"
uv run pytest -m e2e tests/e2e
Remove-Item Env:SWITCHBOARD_E2E
```

Stop the stack gracefully:

```powershell
docker compose -f deploy/compose.yaml down --timeout 15
```

Compose sets `SWITCHBOARD_MOCK_PROVIDER_URL=http://mock-provider:8001`. The hostname is the Compose service name: `localhost` inside the gateway container would incorrectly point back to the gateway container itself.

Copy `.env.example` to `.env` only when local configuration is needed. Never commit `.env` or real credentials.

## Project documents

- [`docs/BUILD_CONTRACT.md`](docs/BUILD_CONTRACT.md) — project source of truth supplied by the owner
- [`docs/architecture.md`](docs/architecture.md) — current and immediately planned architecture
- [`docs/adr/0001-python-fastapi-chat-completions.md`](docs/adr/0001-python-fastapi-chat-completions.md) — initial architecture decision
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — verified implementation status and handoff log
