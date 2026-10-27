FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --locked --no-dev --no-editable \
    && useradd --create-home --uid 10001 switchboard \
    && chown -R switchboard:switchboard /app

USER switchboard

EXPOSE 8000

CMD ["uvicorn", "switchboard.gateway:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
