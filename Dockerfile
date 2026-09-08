FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
COPY --from=ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff /uv /usr/local/bin/uv
ARG WITH_SEMANTIC=1
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    AGENT_AUDIT_PATH=/app/.runtime/runs.sqlite3 \
    AGENT_BUSINESS_PATH=/app/.runtime/business.sqlite3
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY evals ./evals
COPY evaluation ./evaluation
COPY scripts/prepare_embeddings.py ./scripts/prepare_embeddings.py
RUN case "$WITH_SEMANTIC" in \
      0) uv sync --frozen --no-dev --no-editable ;; \
      1) uv sync --frozen --no-dev --no-editable --extra semantic ;; \
      *) echo "WITH_SEMANTIC must be 0 or 1" >&2; exit 2 ;; \
    esac
RUN groupadd --gid 10001 agent && useradd --uid 10001 --gid agent --create-home agent \
    && mkdir -p /app/.runtime /models/bge && chown -R agent:agent /app/.runtime /models/bge
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/v2/health', timeout=3)"
CMD ["uvicorn", "supplychain_agent.api:app", "--host", "0.0.0.0", "--port", "8765"]
