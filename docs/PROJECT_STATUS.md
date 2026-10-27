# Project status

## Current phase

- **Phase:** 0 — Product specification and repository skeleton
- **Subphase:** 0A — Repository contract and development foundation
- **State:** Complete and locally verified; GitHub-hosted CI is pending a future push
- **Updated:** 2026-10-27 (Asia/Calcutta)

## Completed behavior

- Repository is based on the synchronized `main` branch and developed on `codex/phase-0-foundation`.
- Python package uses an installable `src` layout with no custom `PYTHONPATH` requirement.
- Development dependencies and transitive versions are managed by `uv` and a committed lockfile.
- Ruff, strict mypy, pytest, and package-build checks have shared local commands and GitHub Actions CI.
- The owner-supplied project build contract is versioned as `docs/BUILD_CONTRACT.md`.
- Documentation distinguishes implemented foundation work from planned gateway behavior.

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

The checked-in `docs/BUILD_CONTRACT.md` has the same SHA-256 digest as the supplied attachment: `405D3F5F4DD1E5028359690D347FF4669874D8E35FA4636BBD2C6DFB45C75E49`.

## Decisions

- Support Python 3.12+ and verify the minimum supported line with uv-managed CPython 3.12.9. The machine also has system Python 3.14.6, but that interpreter was not used for the recorded suite.
- Use `uv` because it is installed locally and provides reproducible dependency locking and command execution.
- Use strict mypy for static type checking because it is Python-native, mature, and sufficient for the current package; adding a second checker would duplicate feedback without evidence of value.
- Run CI in Phase 0A so every later subphase inherits clean-machine lint, type, test, and build checks.
- Defer CD until there is a deployable application and an explicit destination.
- Keep application dependencies empty until runtime code exists; FastAPI, Uvicorn, and HTTPX will be added in the subphase that first imports them.

## Known limitations and blockers

- No HTTP application, health endpoint, deterministic mock provider, or request flow exists yet.
- Docker and Docker Compose are installed but are not exercised in Phase 0A because no containerized service exists yet.
- CI configuration is locally reviewed but cannot be reported as a successful GitHub run until it is pushed and GitHub Actions executes it.

## Next subphase

Phase 0B will add the minimal FastAPI gateway, a separate deterministic mock-provider application, health endpoints, response contracts, and unit/integration coverage. It will not yet implement Chat Completions proxying or SSE streaming.
