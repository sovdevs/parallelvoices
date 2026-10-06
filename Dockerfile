FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev
# Railway sets PORT. One process, one replica (the rate limiter is in-memory).
CMD ["sh", "-c", "exec uv run --no-sync uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
