# Project status

## Current phase

- **Phase:** 0 — Product specification and repository skeleton
- **Subphase:** 0D — Phase gate, documentation, and pull request
- **State:** Clean-start verification complete; push, PR, and GitHub-hosted CI remain
- **Updated:** 2026-10-27 (Asia/Calcutta)

## Completed behavior

- Repository is based on the synchronized `main` branch and developed on `codex/phase-0-foundation`.
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

## Decisions

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

- The gateway calls only the mock-provider health endpoint; it does not forward generation requests.
- `POST /generate` is a project test contract, not an OpenAI-compatible endpoint.
- GitHub-hosted CI is not yet verified; local success does not predict its final status.
- No deployment target exists, so CD remains intentionally absent.

## Next subphase

Push `codex/phase-0-foundation`, open the pull request without merging it, and verify the exact GitHub Actions and PR state. Phase 1 must not begin in this phase.
