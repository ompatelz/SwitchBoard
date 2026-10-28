# Project status

## Current phase

- **Phase:** 1 — Real working gateway MVP
- **Subphase:** 1D — SDK compatibility and MVP acceptance gate
- **State:** Local acceptance complete; final commit, push, PR, and hosted checks pending
- **Updated:** 2026-10-28 (Asia/Calcutta)

## Completed behavior

- Phase 0 PR #1 merged into `main` at `3f2fc925`; its quality and Compose checks passed.
- Phase 1 work is isolated on `codex/phase-1-gateway-mvp` from that verified merge.
- Strict Pydantic v2 request models accept only `model`, `messages`, and boolean `stream`.
- Text-only `system`, `user`, and `assistant` messages are supported with explicit count and
  content bounds; blank content and unknown fields are rejected.
- OpenAI-shaped non-streaming response contracts cover the completion object, one choice,
  assistant message, finish reason, and usage fields.
- The mock provider exposes `POST /v1/chat/completions` for the same declared subset.
- Canonical validated JSON and SHA-256 produce stable IDs and completion text; a fixed timestamp
  and documented word-count usage fixtures keep tests deterministic.
- `docs/api-contract.md` records supported fields, defaults, validation, unsupported capabilities,
  response structure, and compatibility limitations.
- Public gateway `POST /v1/chat/completions` validates and forwards buffered or streaming requests.
- A minimal `ChatProvider` protocol separates the route from `HttpxMockProvider` without a plugin
  framework.
- FastAPI dependency injection permits a typed provider replacement in tests.
- Readiness and completion forwarding reuse the same lifespan-owned `httpx.AsyncClient`.
- Connect, read, write, and pool timeouts have separate validated environment settings.
- Safe incoming request IDs are preserved; missing or unsafe IDs are replaced, forwarded, and
  returned in response headers and gateway error details.
- Malformed JSON, request validation, connection failure, timeout, provider 4xx, 429, 5xx, and
  invalid provider responses have stable non-sensitive error mappings.
- Buffered provider responses are explicitly closed, the shared client closes at shutdown, and
  cancellation escapes provider error translation.
- `stream: true` returns validated OpenAI-shaped `chat.completion.chunk` SSE events followed by
  `[DONE]`; packet fragments are reassembled before schema validation.
- The provider adapter validates status, content type, and the first event before public HTTP 200.
- Streaming reads are demand-driven for backpressure; normal completion, provider failure, and
  downstream cancellation all close the upstream response.
- Mid-stream failure terminates without `[DONE]`, fabricated usage, retry, fallback, or response
  splicing; clients can distinguish incomplete output from success.
- The mock provider has deterministic normal, delayed, slow, pre-first-failure, and
  mid-stream-failure scenarios plus cleanup counters used by real-socket tests.
- OpenAI Python SDK 3.40.0 is locked as a development-only acceptance dependency; the standard
  client deserializes buffered completions and iterates typed streaming chunks through a custom
  local `/v1` base URL.
- `examples/openai_sdk_chat.py` demonstrates buffered and streaming SDK calls with a harmless
  placeholder key, a five-second client timeout, and SDK retries disabled.
- SDK use does not imply authentication: Phase 1 accepts the header but has no tenant identity.

- Phase 0 development was based on synchronized `main` and isolated on
  `codex/phase-0-foundation` before merge.
- Python package uses an installable `src` layout with no custom `PYTHONPATH` requirement.
- Development dependencies and transitive versions are managed by `uv` and a committed lockfile.
- Ruff, strict mypy, pytest, and package-build checks have shared local commands and GitHub Actions CI.
- The owner-supplied project build contract is versioned as `docs/BUILD_CONTRACT.md`.
- Documentation distinguishes implemented foundation work from planned gateway behavior.
- Gateway application factory with `GET /healthz`.
- Separate mock-provider application factory with `GET /healthz` and `POST /generate`.
- Deterministic SHA-256-derived mock responses for identical validated inputs.
- Strict request bounds and rejection of blank prompts, invalid seeds, models, and unknown fields.
- Unit and in-process HTTP integration tests for success, determinism, and invalid input.
- Typed environment configuration with safe local defaults and Compose service discovery.
- One lifespan-managed shared `httpx.AsyncClient` created at gateway startup and closed at shutdown.
- `GET /readyz` verifies the configured mock-provider health contract and returns stable HTTP 503 on failure.
- One locked, non-root container image reused by both services.
- Docker Compose ordering and health checks for the mock provider and gateway.
- Opt-in real-socket end-to-end test integrated into local instructions and GitHub Actions CI.
- Phase 0 scope audit completed with no future-phase infrastructure or benchmark claims introduced.
- Setup, environment behavior, container networking, and observed failure troubleshooting documented.
- Mermaid diagram added for the actual Phase 0 request and resource-lifecycle flow.
- Unused example environment variables removed so the sample reflects only settings the application reads.
- Compose corrected to build the shared image once and reuse it for both services.

## Verification

Executed on Windows on 2026-10-27 using the committed `uv.lock` and uv-managed CPython 3.12.9:

| Command | Observed result |
| --- | --- |
| `uv lock` | Resolved 13 packages and wrote `uv.lock`. |
| `uv sync --locked --all-groups` | Created `.venv`, installed the package and 12 locked build/development dependencies. |
| `uv run ruff check .` | Passed: `All checks passed!` |
| `uv run ruff format --check .` | Passed: 7 Python files already formatted. |
| `uv run mypy src tests` | Passed: no issues in 2 source files. |
| `uv run pytest` | Passed: 1 test collected and passed. |
| `uv build` | Built both the source distribution and wheel successfully. |
| `uv run python -c "import switchboard; print(switchboard.__version__)"` | Imported the installed package and printed `0.1.0`. |
| `git diff --check` | Passed with no whitespace errors. |

Phase 0B verification performed so far:

| Command or check | Observed result |
| --- | --- |
| `uv lock` and `uv sync --locked --all-groups` | Resolved and installed 30 packages under CPython 3.12.9. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed: 12 Python files already formatted. |
| `uv run mypy src tests` | Passed: no issues in 7 source files. |
| `uv run pytest` | Passed: 10 tests; warnings are treated as errors. |
| `uv build` | Built the source distribution and wheel successfully. |
| Application-factory import check | Created both applications and printed their titles successfully. |
| Real Uvicorn gateway on `127.0.0.1:18000` | Started and returned `{"status":"ok","service":"gateway"}`. |
| Real Uvicorn mock provider on `127.0.0.1:18001` | Started and returned its health response. |
| Two real HTTP `POST /generate` requests | Returned identical JSON, including ID `mock-c4016e8062782e53bafb1713`. |

The post-documentation `git diff --check` also passed without whitespace errors.

Phase 0C verification performed so far:

| Command or check | Observed result |
| --- | --- |
| `uv lock` and `uv sync --locked --all-groups` | Resolved and installed 33 packages under CPython 3.12.9. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed: 16 Python files already formatted. |
| `uv run mypy src tests` | Passed: no issues in 11 source files. |
| `uv run pytest` | Passed: 16 tests and 1 intentional e2e skip; the e2e test runs only against started services. |
| `uv build` | Built the source distribution and wheel successfully. |
| Local real-socket e2e run on ports 18000/18001 | Passed: 1 test. |
| `docker compose ... config --quiet` | Passed. |
| Compose image build | Passed using Python 3.12 slim and uv 0.12.7; installed only 18 runtime packages. |
| Compose health checks | Both `gateway` and `mock-provider` reported healthy. |
| Container e2e smoke test | Passed: gateway liveness/readiness, mock health, and repeated deterministic generation. |
| `docker compose ... down --timeout 15` | Both containers stopped and were removed; the scoped network was removed. |

The final Compose process listing was empty after shutdown, confirming no project containers remained.

Phase 1A verification:

| Command or check | Observed result |
| --- | --- |
| Untouched Phase 0 `uv run ruff check .` | Passed before Phase 1 edits. |
| Untouched Phase 0 `uv run ruff format --check .` | Passed: 16 files already formatted. |
| Untouched Phase 0 `uv run mypy src tests` | Passed: 11 source files checked. |
| Untouched Phase 0 `uv run pytest` | Passed: 16 tests and 1 intentional e2e skip. |
| Focused contract and mock-provider tests | Passed: 24 tests before final boundary additions. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed: 18 Python files already formatted. |
| `uv run mypy src tests` | Passed: 12 source files checked. |
| `uv run pytest` | Passed: 32 tests and 1 intentional e2e skip. |
| `uv build` | Built the source distribution and wheel successfully. |
| `git diff --check` | Passed with no whitespace errors. |

Phase 1B verification:

| Command or check | Observed result |
| --- | --- |
| Focused configuration, provider, request-ID, lifecycle, and gateway tests | Passed: 30 tests. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed: 23 Python files already formatted. |
| `uv run mypy src tests` | Passed: 17 source files checked. |
| `uv run pytest` | Passed: 58 tests and 1 intentional e2e skip. |
| `uv build` | Built the source distribution and wheel successfully. |
| `git diff --check` | Passed with no whitespace errors. |
| Real Uvicorn services on ports 18000/18001 | Started successfully. |
| Real-socket `SWITCHBOARD_E2E=1` test | Passed: 1 test; gateway forwarded to mock provider. |
| Local Uvicorn cleanup check | Ports 18000/18001 and both server process IDs were absent afterward. |
| `docker compose ... config --quiet` | Passed before the engine-dependent startup step. |
| Docker engine | Docker Desktop recovered and reported engine version 29.9.2. |
| Compose image build | Passed from the committed lockfile; installed 18 runtime packages. |
| Compose startup and health checks | Gateway and mock provider both became healthy. |
| Compose real-socket e2e | Passed: 1 test; two gateway completions reached the mock provider over Compose DNS. |
| Container runtime users | Both services ran as non-root user `switchboard`. |
| Compose logs | Gateway and mock-provider health, readiness, generation, and completion requests returned 200. |
| Scoped Compose cleanup | Both containers and the network were removed; final Compose listing was empty. |

Phase 1D verification:

| Command or check | Observed result |
| --- | --- |
| Clean `uv sync --locked --all-groups` in a new isolated environment | Installed 35 locked packages under CPython 3.12.9. |
| Installed-package import check | Printed `openai=3.40.0 switchboard=0.1.0` without custom `PYTHONPATH`. |
| `uv run ruff format --check .` | Passed: 27 Python files already formatted. |
| `uv run ruff check .` | Passed. |
| `uv run mypy src tests examples` | Passed: no issues in 21 source files. |
| `uv run pytest` | Passed: 67 tests and 2 intentional stopped-service e2e skips. |
| Real-loopback streaming integration tests | Passed: completion, failure boundaries, disconnect cancellation, and cleanup. |
| `uv build` | Built the source distribution and wheel successfully. |
| Compose build/startup | Built `switchboard:phase-1`; gateway and mock provider became healthy. |
| Compose e2e suite | Passed: 2 tests covering raw HTTP and OpenAI SDK buffered/streaming calls. |
| SDK example | Buffered and streaming calls returned identical deterministic content. |
| Container runtime users | Both services ran as `uid=10001(switchboard)`. |
| Compose logs and cleanup | No application error appeared; both containers and the scoped network were removed. |
| Tracked-artifact scan | No environment, cache, build output, bytecode, or log artifact is tracked. |
| High-confidence secret scan | No private-key block or common live credential pattern was found. |

Phase 1C verification:

| Command or check | Observed result |
| --- | --- |
| `uv run ruff format --check .` | Passed: 25 Python files already formatted. |
| `uv run ruff check .` | Passed. |
| `uv run mypy src tests` | Passed: no issues in 19 source files. |
| `uv run pytest` | Passed: 67 tests and 1 intentional e2e skip. |
| Real-loopback streaming integration tests | Passed: normal SSE, pre-/mid-stream failures, and downstream-disconnect cleanup. |
| `uv build` | Built the source distribution and wheel successfully. |
| `git diff --check` | Passed with no whitespace errors. |
| Docker engine | Docker Desktop reported engine version 29.9.2. |
| `docker compose -f deploy/compose.yaml config --quiet` | Passed. |
| Compose image build and startup | Passed; both services became healthy from the locked, non-root image. |
| Compose real-socket e2e | Passed: buffered requests and a validated SSE stream reached the mock provider over Compose DNS. |
| Container runtime users | Both services ran as `uid=10001(switchboard)`. |
| Scoped Compose cleanup | Both containers and the network were removed; final Compose listing was empty. |

Phase 0D clean-start verification:

| Command or check | Observed result |
| --- | --- |
| `uv venv --clear --python 3.12 .venv` | Recreated the environment with uv-managed CPython 3.12.9. |
| `uv sync --locked --all-groups` | Installed the project and 31 locked dependencies into the empty environment. |
| Fresh import/factory check | Printed version `0.1.0` and created both application factories without `PYTHONPATH` changes. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed: 16 Python files already formatted. |
| `uv run mypy src tests` | Passed: no issues in 11 source files. |
| `uv run pytest` | Passed: 16 tests and 1 intentional e2e skip. |
| Fresh `uv build` | Built both source and wheel archives after old `dist/` was removed. |
| `docker compose ... build --no-cache` | Passed; one shared image was built with 18 runtime packages. |
| Clean Compose startup | Mock provider and gateway both became healthy. |
| Container e2e smoke | Passed: 1 test. |
| Image runtime user | Verified as non-root user `switchboard`. |
| Graceful Compose stop | Both services logged `Application shutdown complete`; no unclosed-client warning appeared. |
| Scoped Compose removal | Both containers and the Phase 0D network were removed. |
| Tracked-artifact scan | No `.env`, virtual environment, cache, build output, bytecode, or log file is tracked. |
| Secret-like value scan | No credential-like assignments found outside the non-secret build contract text. |
| Branch push | Local and remote `codex/phase-0-foundation` matched at implementation SHA `efda6b4cd596cfb0c459f12d943de81e2d6951c2`. |
| Pull request | [PR #1](https://github.com/ompatelz/SwitchBoard/pull/1) opened as non-draft, open, mergeable, and intentionally unmerged. |
| GitHub Actions `quality` | Passed on both push-triggered and PR-triggered runs for the implementation head. |
| GitHub Actions `compose-smoke` | Passed on both push-triggered and PR-triggered runs for the implementation head. |

## Decisions

- Reject every unknown request field rather than accepting parameters whose behavior is absent.
- Support only `system`, `user`, and `assistant` text messages in the initial contract.
- Accept `stream` only as `false` in Phase 1A; `true` requires the Phase 1C SSE lifecycle.
- Bound model names to 128 characters, messages to 64, and each content string to 32,768
  characters so the validation boundary does not accept obviously inappropriate input sizes.
- Preserve meaningful message whitespace while rejecting whitespace-only content.
- Keep public wire contracts in `contracts.py`; the deterministic provider builder consumes those
  models but does not redefine them.
- Treat mock word counts as experimental fixture metadata, never real tokenizer or billing truth.
- Use one `ChatProvider` protocol with one HTTPX adapter; defer registries and plugin frameworks
  until multiple providers create a demonstrated need.
- Let lifespan own the shared client and let the adapter borrow it, so request handlers never
  create or close the connection pool.
- Configure HTTPX connect, read, write, and pool timeouts independently rather than using one
  ambiguous scalar.
- Map provider rejection, throttling, unavailability, transport failure, and invalid responses to
  distinct codes; never expose upstream response bodies or internal exception text.
- Accept only bounded log-safe request IDs and replace unsafe input instead of reflecting it.
- Do not catch `BaseException` or cancellation exceptions in provider translation.
- Do not retry or fall back in Phase 1B: one gateway request makes at most one provider request.
- Prefetch and validate exactly one SSE event before committing the public streaming response, so
  failures before output retain a truthful JSON status without buffering the whole completion.
- Treat `[DONE]` as the successful terminal marker; EOF or provider failure without it is partial
  and unknown, never an implicit success.
- Let ASGI task cancellation unwind the async generator and close upstream ownership in `finally`;
  do not poll the downstream socket from application code.
- Never retry, fall back, or splice providers after streamed output begins.
- Keep the OpenAI SDK development-only: it proves the public wire contract but is not part of the
  gateway's runtime implementation.
- Use a placeholder SDK key only because the client constructor requires a non-empty value; do
  not describe it as authentication.
- Disable SDK retries in the example and acceptance test so one observed call represents one
  client attempt and the Phase 1 no-retry baseline remains explicit.

- Support Python 3.12+ and verify the minimum supported line with uv-managed CPython 3.12.9. The machine also has system Python 3.14.6, but that interpreter was not used for the recorded suite.
- Use `uv` because it is installed locally and provides reproducible dependency locking and command execution.
- Use strict mypy for static type checking because it is Python-native, mature, and sufficient for the current package; adding a second checker would duplicate feedback without evidence of value.
- Run CI in Phase 0A so every later subphase inherits clean-machine lint, type, test, and build checks.
- Defer CD until there is a deployable application and an explicit destination.
- Add FastAPI, Pydantic, and Uvicorn as direct runtime dependencies now that Phase 0B imports them; keep the Starlette test-client backend `httpx2` development-only.
- Use separate application factories so processes and tests can construct isolated FastAPI instances.
- Keep the mock contract intentionally distinct from Chat Completions to avoid implying gateway compatibility before Phase 1.
- Generate deterministic identities from canonical validated JSON and SHA-256; do not use random values, timestamps, or Python's process-randomized `hash()`.
- Use Starlette's current `httpx2` test-client backend in development. The first test run exposed the deprecation of its `httpx` fallback; the dependency was corrected and warnings now fail tests.
- Defer application-level structured logging until request identifiers and meaningful request events exist. Uvicorn provides process/access logs for the current health and mock endpoints.
- Add classic `httpx` as a runtime dependency for the gateway's pooled `AsyncClient`; retain `httpx2` only for Starlette's current test client.
- Use FastAPI lifespan as the sole owner of the shared client so startup, cancellation, and shutdown have one cleanup boundary.
- Treat `/healthz` as process liveness and `/readyz` as required-upstream readiness.
- Use environment configuration with a local loopback default; Compose overrides it with the `mock-provider` service hostname.
- Reuse one image for both processes and override only the Uvicorn command, avoiding duplicate Dockerfiles.
- Extend CI with a Compose smoke job now that containerized behavior exists; CD remains deferred without a deployment destination.
- Keep `.env.example` limited to variables currently consumed by code; it documents values but is not automatically loaded.
- Build the shared Compose image only from the mock-provider service and reuse the same tag for the gateway.

## Known limitations and blockers

- `POST /generate` is a project test contract, not an OpenAI-compatible endpoint.
- Streaming usage is omitted because the current mock stream does not provide trustworthy usage;
  the gateway does not estimate it.
- There are no retries, fallback providers, authentication, or paid-provider integrations.
- Compatibility covers only the documented Chat Completions subset, not every parameter exposed
  by the OpenAI SDK.
- No deployment target exists, so CD remains intentionally absent.
- The Phase 1 branch is not pushed and has no PR or hosted CI.

## Next subphase

Phase 1 is locally complete once the final integrity checks and cleanup pass. Push the verified
branch, open the Phase 1 PR without merging, inspect visible hosted checks, then stop. Phase 2A is
proposal-only until the owner explicitly starts it.
