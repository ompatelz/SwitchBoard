# Switchboard

Switchboard is an OpenAI-compatible LLM inference gateway that will choose a safe, cost-effective way to fulfill each request and produce reproducible evidence about the quality, cost, latency, and reliability trade-offs behind that choice.

## Why Switchboard exists

LLM gateways can make routing and caching look simple while hiding difficult correctness questions: Was a cached answer actually safe to reuse? Did a retry duplicate cost? Did a streaming disconnect leak a connection? Did a cheaper route harm answer quality? Switchboard is designed to make those decisions explicit, testable, and measurable.

The project is a learning-focused, portfolio-grade backend and ML-systems implementation. Claims will be tied to reproducible tests and experiments rather than aspirational benchmark numbers.

## Current scope: Phase 2 acceptance gate

Phase 0 and Phase 1 are merged. This branch adds bounded mock-provider reliability while
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
  `POST /v1/chat/completions` route;
- gateway `POST /v1/chat/completions` forwarding through a typed provider adapter;
- one reused lifespan-managed HTTPX connection pool with explicit timeout categories;
- safe request-ID acceptance/generation and cross-service propagation; and
- stable non-sensitive errors for invalid input and provider failures;
- OpenAI-compatible SSE chunks and `[DONE]` for `stream: true`;
- honest partial-stream termination plus upstream cleanup on downstream cancellation; and
- verified compatibility with the standard OpenAI Python SDK for buffered and streaming calls.

The gateway supports buffered and streaming Chat Completions for the documented text-only subset.
Phase 2A adds a named provider registry, typed retry decisions, a finite deadline, optional
pre-response fallback to a second mock endpoint, and a process-local circuit breaker. Failure and
streaming semantics are documented in [`docs/failure-model.md`](docs/failure-model.md).
Phase 2B requires a configured bearer API key and adds a tenant-scoped exact Redis cache for
successful buffered calls. Streaming and secondary-provider policies bypass the cache.
Phase 2C adds atomic tenant request windows, bounded worker upstream capacity, and baseline metrics.
Phase 2D adds a documented fault matrix and local measurements. See
[`docs/fault-matrix.md`](docs/fault-matrix.md) and
[`docs/benchmark-results.md`](docs/benchmark-results.md) for exact evidence and limits.

## HTTP contracts

| Service | Method and path | Successful response |
| --- | --- | --- |
| Gateway | `GET /healthz` | `{"status":"ok","service":"gateway"}` |
| Gateway | `GET /readyz` | `{"status":"ready","upstream":"mock-provider"}` when the mock provider is healthy |
| Gateway | `GET /cachez` | Redis health status |
| Gateway | `GET /metrics` | Process-local Prometheus metrics |
| Gateway | `POST /v1/chat/completions` | Validated JSON completion or SSE stream from the configured provider |
| Mock provider | `GET /healthz` | `{"status":"ok","service":"mock-provider"}` |
| Mock provider | `POST /generate` | Stable `id`, `model`, and `text` derived from the validated request |
| Mock provider | `POST /v1/chat/completions` | Deterministic buffered or streaming Chat Completion fixture |

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

## Phase 2C request controls

The gateway now enforces a Redis-backed fixed window per authenticated tenant before cache lookup.
By default, each tenant gets 120 completion requests in a 60-second window that starts with its
first request. Cache hits count. A 429 response includes `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, `X-RateLimit-Reset` (seconds until expiry), and `Retry-After`. If Redis
cannot make the decision, the gateway returns 503 `rate_limit_unavailable` and makes no provider
call. Cache-only command failures still fail open after an allowed decision.

Each worker permits at most 32 active upstream calls or streams by default. A full worker returns
503 `upstream_concurrency_exhausted` immediately. `/metrics` exports process-local Prometheus
metrics with fixed, non-sensitive labels. See [ADR 0004](docs/adr/0004-rate-concurrency-metrics.md)
for window, cleanup, and metric semantics. Token quotas and a dashboard remain deferred.

## Explicit non-goals for Phase 2

Phase 2 does **not** include:

- PostgreSQL, Qdrant, semantic caching, or learned model routing;
- production key administration, token quotas, or real paid providers;
- a dashboard, Kubernetes, Kafka, or paid-provider integration; or
- real-provider performance, cost-saving, or production-readiness claims.

## Verified status

The exact checks run for this subphase are recorded in [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md).
Phase 0, Phase 1, and each Phase 2 subphase are recorded separately in the status
document.

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
uv run mypy src tests examples scripts
uv run pytest
uv build
```

Confirm that the installed package imports normally:

```powershell
uv run python -c "import switchboard; print(switchboard.__version__)"
```

Generate a development key in your shell. Keep the raw key private; configure only its SHA-256
digest on the gateway. The same shell variables are used by Compose and the examples:

```powershell
$keyBytes = [byte[]]::new(32)
[Security.Cryptography.RandomNumberGenerator]::Fill($keyBytes)
$env:SWITCHBOARD_API_KEY = [Convert]::ToBase64String($keyBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
$digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($env:SWITCHBOARD_API_KEY))).ToLowerInvariant()
$env:SWITCHBOARD_TENANT_KEY_HASHES_JSON = @{ dev = $digest } | ConvertTo-Json -Compress
```

For direct local execution, start Redis at `127.0.0.1:6379` or configure
`SWITCHBOARD_REDIS_URL`. If Redis is absent, completion requests return 503 because rate
enforcement fails closed; `/cachez` also reports 503. Never commit the raw key or a real `.env` file.

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
Invoke-RestMethod http://127.0.0.1:8000/cachez
Invoke-WebRequest http://127.0.0.1:8000/metrics
Invoke-RestMethod http://127.0.0.1:8001/healthz
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8001/generate `
  -ContentType application/json `
  -Body '{"prompt":"Explain ASGI","model":"mock-v1","seed":7}'
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/v1/chat/completions `
  -Headers @{ "X-Request-ID" = "readme-example-1"; Authorization = "Bearer $env:SWITCHBOARD_API_KEY" } `
  -ContentType application/json `
  -Body '{"model":"mock-v1","messages":[{"role":"user","content":"Explain ASGI"}]}'
curl.exe --no-buffer http://127.0.0.1:8000/v1/chat/completions `
  -H "Authorization: Bearer $env:SWITCHBOARD_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"mock-v1","messages":[{"role":"user","content":"Explain ASGI"}],"stream":true}'
```

The streaming response ends with `data: [DONE]`. If a partial stream closes without that sentinel,
treat the completion as incomplete; the gateway does not retry or splice another provider after
output begins.

### OpenAI Python SDK

With both local services running, execute the checked-in SDK example:

```powershell
uv run python examples/openai_sdk_chat.py
```

Its essential client configuration is:

```python
import os

from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key=os.environ["SWITCHBOARD_API_KEY"],
    max_retries=0,
    timeout=5.0,
)
```

The SDK sends the configured development key as a bearer token. Disabling SDK retries keeps gateway
attempts observable and avoids confusing client-side
retries with gateway behavior. The complete example closes the SDK client with a context manager
and demonstrates both buffered and streaming calls. This follows the official
[Python client configuration](https://developers.openai.com/api/reference/python) and
[Chat Completions streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
patterns while targeting Switchboard's intentionally smaller contract.

## Docker Compose

Docker Desktop must be running. Set the key variables above, then build and wait for health checks:

```powershell
docker compose -f deploy/compose.yaml up --build --wait --wait-timeout 180
```

Run the real end-to-end smoke test against the published ports:

```powershell
$env:SWITCHBOARD_E2E = "1"
uv run pytest -m e2e tests/e2e
$env:SWITCHBOARD_REDIS_INTEGRATION_URL = "redis://127.0.0.1:6380/15"
uv run pytest -m redis tests/integration/test_redis_cache.py
Remove-Item Env:SWITCHBOARD_REDIS_INTEGRATION_URL
Remove-Item Env:SWITCHBOARD_E2E
```

Stop the stack gracefully:

```powershell
docker compose -f deploy/compose.yaml down --timeout 15
```

Compose sets the mock-provider and Redis service URLs, and requires the configured tenant-key
digest map. Redis is exposed only on host loopback port 6380 for the opt-in integration test.
`localhost` inside the gateway container would point back to the gateway container.

`.env.example` documents provider, cache, auth, request controls, and timeout settings. Set them in the shell or
through a process/container environment; the
application does not silently load `.env` files. Never commit `.env` or real credentials.

## Phase 2 measurements and fault injection

The checked-in benchmark uses real HTTP against the Compose mock provider, a cached gateway,
and an optional second gateway whose secondary-provider policy bypasses the cache. The results
are local mock measurements with the workload, percentiles, error rates, and limitations in
[`docs/benchmark-results.md`](docs/benchmark-results.md). To reproduce them after generating the
development key above:

```powershell
$env:SWITCHBOARD_RATE_LIMIT_REQUESTS = '2000'
docker compose --profile benchmark -f deploy/compose.yaml up --build --wait --wait-timeout 180
uv run python scripts/benchmark_phase2.py
docker compose --profile benchmark -f deploy/compose.yaml stop redis
uv run python scripts/benchmark_phase2.py --redis-outage --output docs/benchmark-redis-outage.json
docker compose --profile benchmark -f deploy/compose.yaml down --timeout 15
```

The stopped-Redis experiment deliberately returns 503 because rate enforcement fails closed.
Normal Compose without `--profile benchmark` does not start the second gateway. The fault matrix
in [`docs/fault-matrix.md`](docs/fault-matrix.md) maps each injected failure to an exact test and
states where the test does not prove a broader production property.

## Troubleshooting

- **Docker reports a missing `dockerDesktopLinuxEngine` pipe:** Docker's CLI is installed, but the Desktop engine is not ready. Start Docker Desktop, wait for `docker ps` to succeed, then retry Compose.
- **Gateway `/healthz` is 200 but `/readyz` is 503:** the gateway process is alive but cannot validate the configured mock-provider health response. Check `SWITCHBOARD_MOCK_PROVIDER_URL` and the mock-provider logs.
- **A completion returns `provider_timeout`:** identify which configured timeout is too short
  before increasing it; do not disable timeout bounds.
- **An incoming request ID changes:** only 1–64 characters from letters, digits, `.`, `_`, and `-`
  are accepted; unsafe values are replaced.
- **The SDK calls `/v1/v1/chat/completions`:** set `base_url` to exactly the gateway URL plus one
  `/v1` suffix, as shown above.
- **A completion returns 401:** configure the server-side digest map and send its matching raw key
  as a bearer token. Missing, invalid, and revoked keys intentionally share one error.
- **`/cachez` is 503:** check Redis and `SWITCHBOARD_REDIS_URL`. Completions fail closed when the
  Redis rate decision is unavailable; `/readyz` checks the mock provider separately.
- **A completion returns `rate_limit_exceeded`:** inspect the limit and reset headers. The Redis
  tenant window includes cache hits and failed provider calls; wait for expiry or adjust the
  configured request policy for local tests.
- **A completion returns `upstream_concurrency_exhausted`:** inspect
  `switchboard_upstream_inflight` and streaming clients. This worker rejects instead of queueing
  when its active upstream calls or streams reach the configured bound.
- **An SDK failure appears more than once:** set `max_retries=0` while diagnosing the Phase 1
  baseline; current SDK defaults may retry selected connection and HTTP failures.
- **The e2e test is skipped:** this is expected during the ordinary unit/integration suite. Start both services and set `SWITCHBOARD_E2E=1` to opt into real-socket testing.
- **`uv sync --locked` reports a stale lockfile:** run `uv lock`, review the dependency diff, and commit `uv.lock` only when the change is intentional.
- **Port 8000 or 8001 is already in use:** stop the conflicting process or change both the published port and the corresponding smoke-test URL.

## Project documents

- [`docs/BUILD_CONTRACT.md`](docs/BUILD_CONTRACT.md) — project source of truth supplied by the owner
- [`docs/architecture.md`](docs/architecture.md) — current and immediately planned architecture
- [`docs/api-contract.md`](docs/api-contract.md) — exact supported Chat Completions subset
- [`docs/adr/0001-python-fastapi-chat-completions.md`](docs/adr/0001-python-fastapi-chat-completions.md) — initial architecture decision
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — verified implementation status and handoff log
- [`docs/fault-matrix.md`](docs/fault-matrix.md) — Phase 2 failure and cleanup gate
- [`docs/benchmark-results.md`](docs/benchmark-results.md) — local mock benchmark and reproduction
