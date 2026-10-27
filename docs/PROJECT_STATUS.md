# Project status

## Current phase

- **Phase:** 0 — Product specification and repository skeleton
- **Subphase:** 0B — Minimal gateway and deterministic mock provider
- **State:** Complete and locally verified; GitHub-hosted CI is pending a future push
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

## Known limitations and blockers

- The gateway does not call the mock provider; no HTTP client lifecycle exists yet.
- `POST /generate` is a project test contract, not an OpenAI-compatible endpoint.
- Docker and Docker Compose are installed but are not exercised in Phase 0B because container wiring belongs to Phase 0C.
- CI configuration is locally reviewed but cannot be reported as a successful GitHub run until it is pushed and GitHub Actions executes it.

## Next subphase

Phase 0C will add a lifespan-managed shared async HTTP client, environment-based service URLs, minimal Dockerfiles, Compose health checks, and an end-to-end smoke test. It will not implement full Chat Completions proxying or SSE streaming.
