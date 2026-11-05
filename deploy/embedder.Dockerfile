FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    OMP_NUM_THREADS=2 \
    SWITCHBOARD_EMBEDDING_MODEL_DIR=/models/bge-small-en-v1.5

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts/prefetch_embedding_model.py ./scripts/prefetch_embedding_model.py

RUN uv sync --locked --no-dev --group embedding --no-editable \
    && python scripts/prefetch_embedding_model.py "$SWITCHBOARD_EMBEDDING_MODEL_DIR" \
    && useradd --create-home --uid 10002 switchboard

ENV HF_HUB_OFFLINE=1

USER switchboard

EXPOSE 8003

CMD ["uvicorn", "switchboard.embedding_service:create_app", "--factory", "--host", "0.0.0.0", "--port", "8003"]
