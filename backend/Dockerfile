# syntax=docker/dockerfile:1
# Backend API image: FastAPI + uvicorn, dependencies locked by uv.lock.

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.13.10 /uv /usr/local/bin/uv
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

# Dependencies first (cached layer), production only. The uv cache lives in a build cache mount,
# so it never ends up in the image.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# Application code: owned by root and read-only for the runtime user.
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY --chmod=755 docker-entrypoint.sh ./
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
