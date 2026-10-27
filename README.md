# Switchboard

Switchboard is an OpenAI-compatible LLM inference gateway that will choose a safe, cost-effective way to fulfill each request and produce reproducible evidence about the quality, cost, latency, and reliability trade-offs behind that choice.

## Why Switchboard exists

LLM gateways can make routing and caching look simple while hiding difficult correctness questions: Was a cached answer actually safe to reuse? Did a retry duplicate cost? Did a streaming disconnect leak a connection? Did a cheaper route harm answer quality? Switchboard is designed to make those decisions explicit, testable, and measurable.

The project is a learning-focused, portfolio-grade backend and ML-systems implementation. Claims will be tied to reproducible tests and experiments rather than aspirational benchmark numbers.

## Current scope: Phase 0A

This branch currently provides only the repository and development foundation:

- an installable `src/switchboard` Python package;
- a reproducible `uv` environment and committed lockfile;
- pytest, Ruff, and strict mypy configuration;
- GitHub Actions CI using the same local quality commands;
- safe example environment values; and
- architecture, decision, build-contract, and status documentation.

No HTTP application or provider is implemented yet. The next subphase will add the smallest FastAPI gateway and deterministic mock-provider applications.

## Explicit non-goals for Phase 0A

Phase 0A does **not** include:

- a `/v1/chat/completions` endpoint or any provider proxying;
- Redis, PostgreSQL, Qdrant, semantic caching, or model routing;
- Docker images or Compose services;
- a dashboard, Kubernetes, Kafka, or paid-provider integration; or
- performance, cost-saving, or production-readiness claims.

## Verified status

The exact checks run for this subphase are recorded in [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md). The package has been built, installed, imported, linted, type-checked, and tested locally without `PYTHONPATH` changes. The locked environment is the authority for local and CI tooling; the GitHub-hosted CI result remains unverified until this branch is pushed.

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

Copy `.env.example` to `.env` only when local configuration is needed. Never commit `.env` or real credentials.

## Project documents

- [`docs/BUILD_CONTRACT.md`](docs/BUILD_CONTRACT.md) — project source of truth supplied by the owner
- [`docs/architecture.md`](docs/architecture.md) — current and immediately planned architecture
- [`docs/adr/0001-python-fastapi-chat-completions.md`](docs/adr/0001-python-fastapi-chat-completions.md) — initial architecture decision
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — verified implementation status and handoff log
