FROM ghcr.io/astral-sh/uv:0.11.19 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV MERIDIAN_ROOT=/app UV_PROJECT_ENVIRONMENT=/app/.venv UV_CACHE_DIR=/app/.cache/uv \
    UV_PYTHON_INSTALL_DIR=/app/.runtime/python UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy UV_CONCURRENT_BUILDS=1 UV_CONCURRENT_DOWNLOADS=4 \
    PYTHONPYCACHEPREFIX=/app/.cache/pycache PYTHONUNBUFFERED=1 \
    TEMP=/app/.tmp TMP=/app/.tmp TMPDIR=/app/.tmp \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
COPY pyproject.toml uv.lock uv.toml README.md ./
COPY backend ./backend
RUN mkdir -p .tmp .runtime .cache && uv sync --locked --no-dev --no-editable && rm -rf /app/.cache/uv
COPY ai_settings.yaml ./
COPY frontend/dist ./frontend/dist
COPY generated ./generated
COPY decisions ./decisions
COPY project-meridian_Avathon ./project-meridian_Avathon
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/api/status', timeout=4)"]
ENTRYPOINT ["/app/.venv/bin/meridian", "--host", "0.0.0.0"]
