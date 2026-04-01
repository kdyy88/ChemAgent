FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_HTTP_TIMEOUT=120

WORKDIR /app

COPY pyproject.toml README.md ./
RUN uv sync --no-dev --no-install-project

COPY . .
RUN uv sync --no-dev


FROM python:3.12-slim AS runner

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         libexpat1 \
         libxrender1 libxext6 libsm6 \
         libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app /app

EXPOSE 3030

# Chemistry-heavy work now runs in a dedicated worker service, so the FastAPI
# process can stay single-worker for consistent in-memory WebSocket sessions.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3030", "--workers", "1", "--limit-max-requests", "1000"]