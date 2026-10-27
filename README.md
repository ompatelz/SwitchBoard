# Switchboard

Switchboard is an OpenAI-compatible LLM inference gateway that will choose a safe, cost-effective way to fulfill each request and produce reproducible evidence about the quality, cost, latency, and reliability trade-offs behind that choice.

## Why Switchboard exists

LLM gateways can make routing and caching look simple while hiding difficult correctness questions: Was a cached answer actually safe to reuse? Did a retry duplicate cost? Did a streaming disconnect leak a connection? Did a cheaper route harm answer quality? Switchboard is designed to make those decisions explicit, testable, and measurable.

The project is a learning-focused, portfolio-grade backend and ML-systems implementation. Claims will be tied to reproducible tests and experiments rather than aspirational benchmark numbers.

## Current scope: Phase 1A

Phase 0 is merged and verified. This branch adds the first Phase 1 contract increment while
preserving the runnable two-service foundation:

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
- one non-root container image plus Docker Compose health checks for both services;
- strict Pydantic v2 models for the documented text-only Chat Completions subset; and
- a deterministic OpenAI-shaped non-streaming fixture at the mock provider's
  `POST /v1/chat/completions` route.

The public gateway does not forward Chat Completions yet. That HTTP provider-adapter path belongs
to Phase 1B; SSE belongs to Phase 1C.

## HTTP contracts

| Service | Method and path | Successful response |
| --- | --- | --- |
| Gateway | `GET /healthz` | `{"status":"ok","service":"gateway"}` |
| Gateway | `GET /readyz` | `{"status":"ready","upstream":"mock-provider"}` when the mock provider is healthy |
| Mock provider | `GET /healthz` | `{"status":"ok","service":"mock-provider"}` |
| Mock provider | `POST /generate` | Stable `id`, `model`, and `text` derived from the validated request |
| Mock provider | `POST /v1/chat/completions` | Deterministic non-streaming Chat Completion fixture |

`POST /generate` accepts this deliberately small request:

```json
{
  "prompt": "Explain ASGI",
  "model": "mock-v1",
  "seed": 7
}
```

`prompt` is trimmed and must contain 1–4096 characters. `model` can only be `mock-v1`; `seed` must be an integer from 0 through 4,294,967,295. Unknown fields are rejected. Invalid requests currently use FastAPI's documented validation response with HTTP `422`; this is a mock-only contract, not an OpenAI error-compatibility claim.

The exact supported Chat Completions fields, limits, and response shape are documented in
[`docs/api-contract.md`](docs/api-contract.md).

## Explicit non-goals for Phase 1A

Phase 1A does **not** include:

- gateway forwarding for `/v1/chat/completions`;
- Redis, PostgreSQL, Qdrant, semantic caching, or model routing;
- provider adapters, stable gateway error translation, retries, or SSE streaming;
- a dashboard, Kubernetes, Kafka, or paid-provider integration; or
- performance, cost-saving, or production-readiness claims.

## Verified status

The exact checks run for this subphase are recorded in [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md).
Phase 0's local, container, and hosted checks passed before merge. Phase 1A's contract suite is
verified locally; this branch has not been pushed and has no hosted Phase 1 checks yet.

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

`.env.example` documents the two environment variables currently read by the gateway. Set them in the shell or through a process/container environment; the application does not silently load `.env` files. Never commit `.env` or real credentials.

## Troubleshooting

- **Docker reports a missing `dockerDesktopLinuxEngine` pipe:** Docker's CLI is installed, but the Desktop engine is not ready. Start Docker Desktop, wait for `docker ps` to succeed, then retry Compose.
- **Gateway `/healthz` is 200 but `/readyz` is 503:** the gateway process is alive but cannot validate the configured mock-provider health response. Check `SWITCHBOARD_MOCK_PROVIDER_URL` and the mock-provider logs.
- **The e2e test is skipped:** this is expected during the ordinary unit/integration suite. Start both services and set `SWITCHBOARD_E2E=1` to opt into real-socket testing.
- **`uv sync --locked` reports a stale lockfile:** run `uv lock`, review the dependency diff, and commit `uv.lock` only when the change is intentional.
- **Port 8000 or 8001 is already in use:** stop the conflicting process or change both the published port and the corresponding smoke-test URL.

## Project documents

- [`docs/BUILD_CONTRACT.md`](docs/BUILD_CONTRACT.md) — project source of truth supplied by the owner
- [`docs/architecture.md`](docs/architecture.md) — current and immediately planned architecture
- [`docs/api-contract.md`](docs/api-contract.md) — exact supported Chat Completions subset
- [`docs/adr/0001-python-fastapi-chat-completions.md`](docs/adr/0001-python-fastapi-chat-completions.md) — initial architecture decision
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — verified implementation status and handoff log
